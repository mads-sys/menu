# services/command_builder.py

import os
import html
import shlex
import re
import logging
import time
from typing import Dict, Tuple, Optional, Any

try:
    from config import SITE_CATEGORIES_CONFIG, AI_APPLICATION_PROCESSES
except ImportError:
    SITE_CATEGORIES_CONFIG = {}
    AI_APPLICATION_PROCESSES = []

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
        'no_sudo': kwargs.get('no_sudo', False),
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

SCRIPTS_CLIENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts_client')
_SCRIPT_CACHE = {}

# --- Carregar Scripts Externos ---
def _load_script(filename: str) -> str:
    """Carrega um script a partir de scripts_client/ ou da raiz do projeto, com cache em memória."""
    if filename in _SCRIPT_CACHE:
        return _SCRIPT_CACHE[filename]
    
    candidates = [
        os.path.join(SCRIPTS_CLIENT_DIR, filename),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        filename
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    _SCRIPT_CACHE[filename] = content
                    return content
            except Exception as e:
                logging.error(f"Erro ao ler script {path}: {e}")

    logging.error(f"Não foi possível carregar o script {filename}. Buscado em: {candidates}")
    return f"echo 'ERRO FATAL: Script {filename} ausente no servidor'; exit 1;"

# Scripts de ambiente e periféricos
GSETTINGS_ENV_SETUP = _load_script('setup_gsettings_env.sh')
MANAGE_RIGHT_CLICK_SCRIPT = _load_script('manage_right_click.sh')
MANAGE_PERIPHERALS_SCRIPT = _load_script('manage_peripherals.sh')
X11_ENV_SETUP = _load_script('setup_x11_env.sh')
UPDATE_MANAGER_SCRIPT = _load_script('update_manager.py')

# Scripts clientes de interface gráfica, overlays e alertas modulares
POPUP_MESSAGE_OVERLAY_SCRIPT = _load_script('popup_message_overlay.py')
SILENCE_ALERT_PYTHON_SCRIPT = _load_script('silence_alert_overlay.py')
TTS_PYTHON_SCRIPT = _load_script('play_tts_speech.py')
RESTORE_PERIPHERALS_SH_SCRIPT = _load_script('restore_peripherals.sh')
FULLSCREEN_LOCK_OVERLAY_PYTHON_SCRIPT = _load_script('fullscreen_lock_overlay.py')
SEMAFORO_OVERLAY_SCRIPT = _load_script('semaforo_overlay.py')
CELEBRAR_OVERLAY_SCRIPT = _load_script('celebrar_overlay.py')

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

    # Calcula a diferença de horário em relação ao servidor
    try:
        remote_ts = int(info['remote_time'])
        server_ts = int(time.time())
        offset = remote_ts - server_ts
        info['offset'] = offset
        # Cria uma string legível como "+5s" ou "-120s"
        prefix = "+" if offset >= 0 else ""
        info['offset_readable'] = f"{prefix}{offset}s"
        info['remote_time'] = time.strftime('%H:%M:%S', time.localtime(remote_ts))
    except (ValueError, KeyError): pass
        
    return info

@register_command('enviar_mensagem', 'Enviar Mensagem', 'Ações Remotas', icon='message-square', require_field='message-group')
def build_send_message_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Constrói o comando para exibir uma mensagem pop-up de aviso estilizada nas máquinas dos alunos."""
    message = data.get('message')
    if not message:
        return None, {"success": False, "message": "O campo de mensagem não pode estar vazio."}

    raw_msg = str(message).strip()
    safe_msg = shlex.quote(raw_msg)
    target_user = data.get('target_user') or ''
    target_disp = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''

    core_logic = f"""
        # 1. Identificação precisa de usuário e display específico no ambiente Multiseat
        REQ_USER={safe_user}
        REQ_DISP={safe_disp}

        # 2. Escreve o script Python de janela gráfica com triplo fallback (GTK3 -> Tkinter -> Zenity)
        cat <<'EOF' > /tmp/popup_message_overlay.py
{POPUP_MESSAGE_OVERLAY_SCRIPT.strip()}
EOF

        chmod 777 /tmp/popup_message_overlay.py 2>/dev/null || chmod +x /tmp/popup_message_overlay.py

        # Garante encerramento de travas/bloqueios anteriores e limpa arquivos de flag
        rm -f /tmp/lock_overlay_active 2>/dev/null || true
        pkill -f "fullscreen_lock_overlay.py" 2>/dev/null || true
        pkill -9 -f "popup_message_overlay.py" 2>/dev/null || true

        # Acorda dispositivos USB HID no kernel e remove autosuspend
        if [ -d /sys/bus/usb/devices ]; then
            for f in /sys/bus/usb/devices/*/power/control; do [ -w "$f" ] && echo on > "$f" 2>/dev/null || true; done
            for f in /sys/bus/usb/devices/*/power/autosuspend; do [ -w "$f" ] && echo -1 > "$f" 2>/dev/null || true; done
        fi
        udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true

        # 3. Descobrir todos os displays X11 ativos na máquina
        if [ -n "$REQ_DISP" ]; then
            DISPLAYS="$REQ_DISP"
        else
            DISPLAYS=$(ls -1 /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | sort -u)
            [ -z "$DISPLAYS" ] && DISPLAYS=":0"
        fi

        # 4. Exibir aviso em todos os displays e sessões ativas no Multiseat
        for d in $DISPLAYS; do
            D_NUM=$(echo "$d" | tr -d ':')

            SEAT_USER=""
            SEAT_UID=""
            SEAT_XAUTH=""
            SEAT_DBUS=""

            # A. Descobre via processos de sessão gráfica rodando neste display específico (/proc/*/environ)
            for pid in $(pgrep -f "cinnamon-session|gnome-session|xfce4-session|mate-session|lxsession|openbox|startplasma|plasma|Xorg|Xephyr|xinit|lightdm|gdm" 2>/dev/null); do
                [ ! -r "/proc/$pid/environ" ] && continue
                p_disp=$(awk -v RS='\\0' '/^DISPLAY=/ {{ sub(/^DISPLAY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                if [ "$p_disp" = "$d" ] || [ "$p_disp" = ":$D_NUM" ] || [ "$p_disp" = "$d.0" ]; then
                    p_u=$(awk -v RS='\\0' '/^USER=/ {{ sub(/^USER=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                    [ -z "$p_u" ] && p_u=$(ps -o user= -p "$pid" 2>/dev/null)
                    if [ -n "$p_u" ] && [ "$p_u" != "root" ] && [ "$p_u" != "lightdm" ] && [ "$p_u" != "gdm" ]; then
                        SEAT_USER="$p_u"
                        SEAT_UID=$(id -u "$p_u" 2>/dev/null)
                        SEAT_XAUTH=$(awk -v RS='\\0' '/^XAUTHORITY=/ {{ sub(/^XAUTHORITY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        SEAT_DBUS=$(awk -v RS='\\0' '/^DBUS_SESSION_BUS_ADDRESS=/ {{ sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        break
                    fi
                fi
            done

            # B. Se ainda não achou o usuário, busca via 'who' e sessões ativas
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | grep -E "(:$D_NUM\\b|\\($d\\))" | awk '{{print $1}}' | head -n 1)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(awk -F: -v uid="$((1000 + D_NUM))" '$3 == uid {{print $1}}' /etc/passwd 2>/dev/null)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | awk '{{print $1}}' | head -n 1)
            fi
            [ -z "$SEAT_USER" ] && SEAT_USER="aluno"
            [ -z "$SEAT_UID" ] && SEAT_UID=$(id -u "$SEAT_USER" 2>/dev/null)

            # Se a ação foi solicitada para um usuário específico, ignora outros displays
            if [ -n "$REQ_USER" ] && [ "$SEAT_USER" != "$REQ_USER" ]; then
                continue
            fi

            # C. Resolução completa e prioritária do XAUTHORITY para este display
            D_XAUTH=""
            if [ -n "$SEAT_XAUTH" ] && [ -f "$SEAT_XAUTH" ]; then
                D_XAUTH="$SEAT_XAUTH"
            fi

            if [ -z "$D_XAUTH" ]; then
                for candidate in \
                    "/var/run/lightdm/root/$d" \
                    "/var/run/lightdm/root/:$D_NUM" \
                    "/run/lightdm/root/$d" \
                    "/run/lightdm/root/:$D_NUM" \
                    "/var/run/lightdm/authority/$D_NUM" \
                    "/run/lightdm/authority/$D_NUM" \
                    "/run/user/$SEAT_UID/.Xauthority" \
                    "/run/user/$SEAT_UID/gdm/Xauthority" \
                    "/run/user/$SEAT_UID/.mutter-Xwayland-Xauthority" \
                    "/home/$SEAT_USER/.Xauthority" \
                    "/tmp/.Xauthority-$SEAT_USER" \
                    "/tmp/.Xauthority-$D_NUM"; do
                    if [ -f "$candidate" ]; then D_XAUTH="$candidate"; break; fi
                done
            fi

            if [ -z "$D_XAUTH" ] && [ -n "$SEAT_UID" ]; then
                D_XAUTH=$(find /run/user/$SEAT_UID /home/$SEAT_USER /var/run/lightdm /run/lightdm -name "*$D_NUM*" -o -name "*Xauthority*" 2>/dev/null | head -n 1)
            fi
            [ -z "$D_XAUTH" ] && D_XAUTH="$XAUTHORITY"

            # D. Resolução de DBUS
            if [ -z "$SEAT_DBUS" ] && [ -n "$SEAT_UID" ] && [ -S "/run/user/$SEAT_UID/bus" ]; then
                SEAT_DBUS="unix:path=/run/user/$SEAT_UID/bus"
            fi

            # E. Libera acesso ao display local via xhost
            DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost + 2>/dev/null || true
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || true
            fi

            # F. Garante que teclado e mouse estejam 100% ATIVOS, DESBLOQUEADOS e REANEXADOS aos masters
            if command -v xinput &>/dev/null; then
                MASTER_KBD=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/Virtual core keyboard|master keyboard/ {{for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {{split($i,a,"="); print a[2]}}}}' | head -n 1)
                [ -z "$MASTER_KBD" ] && MASTER_KBD=3

                MASTER_PTR=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/Virtual core pointer|master pointer/ {{for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {{split($i,a,"="); print a[2]}}}}' | head -n 1)
                [ -z "$MASTER_PTR" ] && MASTER_PTR=2

                MASTER_IDS=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/master/ {{ for (i=1; i<=NF; i++) if ($i ~ /^id=[0-9]+$/) {{ split($i, a, "="); print a[2]; }} }}')
                for m_id in $MASTER_IDS; do
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput enable "$m_id" 2>/dev/null || true
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput set-prop "$m_id" "Device Enabled" 1 2>/dev/null || true
                done

                ALL_IDS=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list --id-only 2>/dev/null || true)
                for id in $ALL_IDS; do
                    DEV_NAME=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list --name-only "$id" 2>/dev/null || true)
                    if echo "$DEV_NAME" | grep -qi "XTEST"; then continue; fi
                    if echo " $MASTER_IDS " | grep -q " $id "; then continue; fi

                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput enable "$id" 2>/dev/null || true
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput set-prop "$id" "Device Enabled" 1 2>/dev/null || true

                    DEV_INFO=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list "$id" 2>/dev/null || true)
                    if echo "$DEV_INFO" | grep -qi "KeyClass" || echo "$DEV_NAME" | grep -qi -E "keyboard|key|kbd"; then
                        DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput reattach "$id" "$MASTER_KBD" 2>/dev/null || true
                    fi
                    if echo "$DEV_INFO" | grep -qi -E "ButtonClass|ValuatorClass" || echo "$DEV_NAME" | grep -qi -E "mouse|pointer|touchpad|trackpoint|touchscreen"; then
                        DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput reattach "$id" "$MASTER_PTR" 2>/dev/null || true
                    fi
                done
                DISPLAY="$d" XAUTHORITY="$D_XAUTH" setxkbmap br 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" setxkbmap us 2>/dev/null || true
            fi

            # G. Dispara janela gráfica no display
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ] && [ "$SEAT_USER" != "lightdm" ]; then
                sudo -u "$SEAT_USER" env DISPLAY="$d" XAUTHORITY="$D_XAUTH" DBUS_SESSION_BUS_ADDRESS="$SEAT_DBUS" nohup python3 /tmp/popup_message_overlay.py {safe_msg} </dev/null >/dev/null 2>&1 &
            else
                nohup env DISPLAY="$d" XAUTHORITY="$D_XAUTH" DBUS_SESSION_BUS_ADDRESS="$SEAT_DBUS" python3 /tmp/popup_message_overlay.py {safe_msg} </dev/null >/dev/null 2>&1 &
            fi
        done

        echo "Mensagem enviada com sucesso para as sessões do multiseat."
    """
    
    full_command = X11_ENV_SETUP + core_logic
    return full_command, None

@register_command('fechar_mensagem', 'Fechar Pop-up de Aviso', 'Ações Remotas', icon='x-square')
def build_close_message_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Fecha e remove a janela pop-up de aviso de todas as sessões e displays."""
    script = X11_ENV_SETUP + f"""
        pkill -9 -f "popup_message_overlay.py" 2>/dev/null || true
        pkill -9 -f "silence_alert_overlay.py" 2>/dev/null || true
        pkill -9 -f "zenity --info --title=📢 RECADO" 2>/dev/null || true
        pkill -9 -f "zenity --info --title=🤫 SILÊNCIO" 2>/dev/null || true
        rm -f /tmp/popup_message_overlay.py /tmp/silence_alert_overlay.py 2>/dev/null || true
        echo "Janela de mensagem fechada com sucesso."
        exit 0
    """
    return script, None

# SILENCE_ALERT_PYTHON_SCRIPT carregado via scripts_client/silence_alert_overlay.py

@register_command('pedir_silencio', 'Pedir Silêncio (Alerta Piscante)', 'Ações de Aula', icon='volume-x')
def build_pedir_silencio_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Exibe um alerta visual piscante de alta prioridade pedindo silêncio imediato na máquina do aluno
    e muta o áudio do sistema. Nunca desloga a sessão do aluno.
    """
    target_user = data.get('target_user') or ''
    target_disp = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''

    custom_msg = data.get('message') or "O professor solicitou silêncio imediato e atenção de todos na sala de aula."
    safe_msg = shlex.quote(str(custom_msg).strip())

    core_logic = f"""
        # 1. Silencia o áudio imediatamente
        pactl set-sink-mute @DEFAULT_SINK@ 1 2>/dev/null || amixer set Master mute 2>/dev/null || true

        # 2. Resolução de usuário e display no Multiseat
        REQ_USER={safe_user}
        REQ_DISP={safe_disp}

        # 3. Escreve script Python com animação piscante e orientação pedagógica
        cat <<'EOF' > /tmp/silence_alert_overlay.py
""" + SILENCE_ALERT_PYTHON_SCRIPT.strip() + f"""
EOF

        chmod 777 /tmp/silence_alert_overlay.py 2>/dev/null || chmod +x /tmp/silence_alert_overlay.py
        pkill -9 -f "silence_alert_overlay.py" 2>/dev/null || true

        # 4. Descobrir todos os displays X11 ativos na máquina
        if [ -n "$REQ_DISP" ]; then
            DISPLAYS="$REQ_DISP"
        else
            DISPLAYS=$(ls -1 /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | sort -u)
            [ -z "$DISPLAYS" ] && DISPLAYS=":0"
        fi

        # 5. Exibir alerta piscante de silêncio em todos os displays e sessões do Multiseat
        for d in $DISPLAYS; do
            D_NUM=$(echo "$d" | tr -d ':')

            SEAT_USER=""
            SEAT_UID=""
            SEAT_XAUTH=""
            SEAT_DBUS=""

            # A. Descobre via processos de sessão gráfica rodando neste display específico (/proc/*/environ)
            for pid in $(pgrep -f "cinnamon-session|gnome-session|xfce4-session|mate-session|lxsession|openbox|startplasma|plasma|Xorg|Xephyr|xinit|lightdm|gdm" 2>/dev/null); do
                [ ! -r "/proc/$pid/environ" ] && continue
                p_disp=$(awk -v RS='\\0' '/^DISPLAY=/ {{ sub(/^DISPLAY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                if [ "$p_disp" = "$d" ] || [ "$p_disp" = ":$D_NUM" ] || [ "$p_disp" = "$d.0" ]; then
                    p_u=$(awk -v RS='\\0' '/^USER=/ {{ sub(/^USER=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                    [ -z "$p_u" ] && p_u=$(ps -o user= -p "$pid" 2>/dev/null)
                    if [ -n "$p_u" ] && [ "$p_u" != "root" ] && [ "$p_u" != "lightdm" ] && [ "$p_u" != "gdm" ]; then
                        SEAT_USER="$p_u"
                        SEAT_UID=$(id -u "$p_u" 2>/dev/null)
                        SEAT_XAUTH=$(awk -v RS='\\0' '/^XAUTHORITY=/ {{ sub(/^XAUTHORITY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        SEAT_DBUS=$(awk -v RS='\\0' '/^DBUS_SESSION_BUS_ADDRESS=/ {{ sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        break
                    fi
                fi
            done

            # B. Se ainda não achou o usuário, busca via 'who' e sessões ativas
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | grep -E "(:$D_NUM\\b|\\($d\\))" | awk '{{print $1}}' | head -n 1)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(awk -F: -v uid="$((1000 + D_NUM))" '$3 == uid {{print $1}}' /etc/passwd 2>/dev/null)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | awk '{{print $1}}' | head -n 1)
            fi
            [ -z "$SEAT_USER" ] && SEAT_USER="aluno"
            [ -z "$SEAT_UID" ] && SEAT_UID=$(id -u "$SEAT_USER" 2>/dev/null)

            # Se a ação foi solicitada para um usuário específico, ignora outros displays
            if [ -n "$REQ_USER" ] && [ "$SEAT_USER" != "$REQ_USER" ]; then
                continue
            fi

            # C. Resolução completa e prioritária do XAUTHORITY para este display
            D_XAUTH=""
            if [ -n "$SEAT_XAUTH" ] && [ -f "$SEAT_XAUTH" ]; then
                D_XAUTH="$SEAT_XAUTH"
            fi

            if [ -z "$D_XAUTH" ]; then
                for candidate in \
                    "/var/run/lightdm/root/$d" \
                    "/var/run/lightdm/root/:$D_NUM" \
                    "/run/lightdm/root/$d" \
                    "/run/lightdm/root/:$D_NUM" \
                    "/var/run/lightdm/authority/$D_NUM" \
                    "/run/lightdm/authority/$D_NUM" \
                    "/run/user/$SEAT_UID/.Xauthority" \
                    "/run/user/$SEAT_UID/gdm/Xauthority" \
                    "/run/user/$SEAT_UID/.mutter-Xwayland-Xauthority" \
                    "/home/$SEAT_USER/.Xauthority" \
                    "/tmp/.Xauthority-$SEAT_USER" \
                    "/tmp/.Xauthority-$D_NUM"; do
                    if [ -f "$candidate" ]; then D_XAUTH="$candidate"; break; fi
                done
            fi

            if [ -z "$D_XAUTH" ] && [ -n "$SEAT_UID" ]; then
                D_XAUTH=$(find /run/user/$SEAT_UID /home/$SEAT_USER /var/run/lightdm /run/lightdm -name "*$D_NUM*" -o -name "*Xauthority*" 2>/dev/null | head -n 1)
            fi
            [ -z "$D_XAUTH" ] && D_XAUTH="$XAUTHORITY"

            # D. Resolução de DBUS
            if [ -z "$SEAT_DBUS" ] && [ -n "$SEAT_UID" ] && [ -S "/run/user/$SEAT_UID/bus" ]; then
                SEAT_DBUS="unix:path=/run/user/$SEAT_UID/bus"
            fi

            # E. Libera acesso ao display local via xhost
            DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost + 2>/dev/null || true
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || true
            fi

            # F. Garante que teclado e mouse estejam 100% ATIVOS, DESBLOQUEADOS e REANEXADOS aos masters
            if command -v xinput &>/dev/null; then
                MASTER_KBD=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/Virtual core keyboard|master keyboard/ {{for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {{split($i,a,"="); print a[2]}}}}' | head -n 1)
                [ -z "$MASTER_KBD" ] && MASTER_KBD=3

                MASTER_PTR=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/Virtual core pointer|master pointer/ {{for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {{split($i,a,"="); print a[2]}}}}' | head -n 1)
                [ -z "$MASTER_PTR" ] && MASTER_PTR=2

                MASTER_IDS=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/master/ {{ for (i=1; i<=NF; i++) if ($i ~ /^id=[0-9]+$/) {{ split($i, a, "="); print a[2]; }} }}')
                for m_id in $MASTER_IDS; do
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput enable "$m_id" 2>/dev/null || true
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput set-prop "$m_id" "Device Enabled" 1 2>/dev/null || true
                done

                ALL_IDS=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list --id-only 2>/dev/null || true)
                for id in $ALL_IDS; do
                    DEV_NAME=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list --name-only "$id" 2>/dev/null || true)
                    if echo "$DEV_NAME" | grep -qi "XTEST"; then continue; fi
                    if echo " $MASTER_IDS " | grep -q " $id "; then continue; fi

                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput enable "$id" 2>/dev/null || true
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput set-prop "$id" "Device Enabled" 1 2>/dev/null || true

                    DEV_INFO=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list "$id" 2>/dev/null || true)
                    if echo "$DEV_INFO" | grep -qi "KeyClass" || echo "$DEV_NAME" | grep -qi -E "keyboard|key|kbd"; then
                        DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput reattach "$id" "$MASTER_KBD" 2>/dev/null || true
                    fi
                    if echo "$DEV_INFO" | grep -qi -E "ButtonClass|ValuatorClass" || echo "$DEV_NAME" | grep -qi -E "mouse|pointer|touchpad|trackpoint|touchscreen"; then
                        DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput reattach "$id" "$MASTER_PTR" 2>/dev/null || true
                    fi
                done
                DISPLAY="$d" XAUTHORITY="$D_XAUTH" setxkbmap br 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" setxkbmap us 2>/dev/null || true
            fi

            # G. Dispara janela gráfica de silêncio no display
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ] && [ "$SEAT_USER" != "lightdm" ]; then
                sudo -u "$SEAT_USER" env DISPLAY="$d" XAUTHORITY="$D_XAUTH" DBUS_SESSION_BUS_ADDRESS="$SEAT_DBUS" nohup python3 /tmp/silence_alert_overlay.py {safe_msg} </dev/null >/dev/null 2>&1 &
            else
                nohup env DISPLAY="$d" XAUTHORITY="$D_XAUTH" DBUS_SESSION_BUS_ADDRESS="$SEAT_DBUS" python3 /tmp/silence_alert_overlay.py {safe_msg} </dev/null >/dev/null 2>&1 &
            fi
        done

        echo "Alerta piscante de silêncio exibido com sucesso em todas as estações (sem deslogar)."
    """
    return X11_ENV_SETUP + core_logic, None
# TTS_PYTHON_SCRIPT carregado via scripts_client/play_tts_speech.py

@register_command('sintetizar_voz', 'Voz do Professor (Sintetizador TTS)', 'Ações de Aula', icon='volume-2')
def build_sintetizar_voz_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Reproduz mensagem de voz falada em Português (BR) nas caixas de som ou fones de ouvido dos alunos.
    Usa síntese de alta fidelidade com fallback inteligente para Speech Dispatcher / espeak.
    """
    target_user = data.get('target_user') or ''
    target_disp = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''

    custom_msg = data.get('message') or "Atenção alunos: por favor, prestem atenção nas orientações do professor."
    safe_msg = shlex.quote(str(custom_msg).strip())

    core_logic = f"""
        # 1. Desmuta o áudio da máquina
        pactl set-sink-mute @DEFAULT_SINK@ 0 2>/dev/null || amixer set Master unmute 2>/dev/null || true
        pactl set-sink-volume @DEFAULT_SINK@ 95% 2>/dev/null || amixer set Master 95% 2>/dev/null || true

        # 2. Escreve script Python de reprodução TTS
        cat <<'EOF' > /tmp/play_tts_speech.py
{TTS_PYTHON_SCRIPT.strip()}
EOF
        chmod 777 /tmp/play_tts_speech.py 2>/dev/null || chmod +x /tmp/play_tts_speech.py

        # 3. Executa a reprodução para as sessões de áudio ativas
        REQ_USER={safe_user}
        if [ -n "$REQ_USER" ] && id "$REQ_USER" &>/dev/null; then
            USER_ID=$(id -u "$REQ_USER")
            sudo -u "$REQ_USER" XDG_RUNTIME_DIR="/run/user/$USER_ID" PULSE_SERVER="unix:/run/user/$USER_ID/pulse/native" python3 /tmp/play_tts_speech.py {safe_msg} 2>/dev/null || python3 /tmp/play_tts_speech.py {safe_msg} 2>/dev/null || true
        else
            python3 /tmp/play_tts_speech.py {safe_msg} 2>/dev/null || true
        fi
    """
    return X11_ENV_SETUP + core_logic, None

@register_command('abrir_site', 'Abrir URL / Site no Navegador', 'Ações Remotas', icon='globe', require_field='url-group')
def build_open_site_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Constrói o comando para abrir uma URL no navegador de todas as sessões e displays ativos (multiseat)."""
    url = data.get('url') or data.get('site_url') or data.get('message')
    if not url:
        return None, {"success": False, "message": "O campo de URL/Site não pode estar vazio."}
    
    url = url.strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        url = 'http://' + url

    safe_url = shlex.quote(url)
    target_user = data.get('target_user') or ''
    target_disp = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''

    core_logic = f"""
        REQ_USER={safe_user}
        REQ_DISP={safe_disp}

        # 1. Identifica os displays gráficos ativos na máquina
        if [ -n "$REQ_DISP" ]; then
            DISPLAYS="$REQ_DISP"
        else
            DISPLAYS=$(ls -1 /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | sort -u)
            [ -z "$DISPLAYS" ] && DISPLAYS=":0"
        fi

        LAUNCHED_COUNT=0

        for d in $DISPLAYS; do
            D_NUM=$(echo "$d" | tr -d ':')

            SEAT_USER=""
            SEAT_UID=""
            SEAT_XAUTH=""
            SEAT_DBUS=""

            # A. Descobre usuário da sessão gráfica neste display
            for pid in $(pgrep -f "cinnamon-session|gnome-session|xfce4-session|mate-session|lxsession|openbox|startplasma|plasma|Xorg|Xephyr|xinit|lightdm|gdm" 2>/dev/null); do
                [ ! -r "/proc/$pid/environ" ] && continue
                p_disp=$(awk -v RS='\\0' '/^DISPLAY=/ {{ sub(/^DISPLAY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                if [ "$p_disp" = "$d" ] || [ "$p_disp" = ":$D_NUM" ] || [ "$p_disp" = "$d.0" ]; then
                    p_u=$(awk -v RS='\\0' '/^USER=/ {{ sub(/^USER=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                    [ -z "$p_u" ] && p_u=$(ps -o user= -p "$pid" 2>/dev/null)
                    if [ -n "$p_u" ] && [ "$p_u" != "root" ] && [ "$p_u" != "lightdm" ] && [ "$p_u" != "gdm" ]; then
                        SEAT_USER="$p_u"
                        SEAT_UID=$(id -u "$p_u" 2>/dev/null)
                        SEAT_XAUTH=$(awk -v RS='\\0' '/^XAUTHORITY=/ {{ sub(/^XAUTHORITY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        SEAT_DBUS=$(awk -v RS='\\0' '/^DBUS_SESSION_BUS_ADDRESS=/ {{ sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        break
                    fi
                fi
            done

            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | grep -E "(:$D_NUM\\b|\\($d\\))" | awk '{{print $1}}' | head -n 1)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(awk -F: -v uid="$((1000 + D_NUM))" '$3 == uid {{print $1}}' /etc/passwd 2>/dev/null)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | awk '{{print $1}}' | head -n 1)
            fi
            [ -z "$SEAT_USER" ] && SEAT_USER="aluno"
            [ -z "$SEAT_UID" ] && SEAT_UID=$(id -u "$SEAT_USER" 2>/dev/null)

            # Filtra por usuário se especificado
            if [ -n "$REQ_USER" ] && [ "$SEAT_USER" != "$REQ_USER" ]; then
                continue
            fi

            # B. Resolução de XAUTHORITY
            D_XAUTH=""
            if [ -n "$SEAT_XAUTH" ] && [ -f "$SEAT_XAUTH" ]; then
                D_XAUTH="$SEAT_XAUTH"
            fi
            if [ -z "$D_XAUTH" ]; then
                for candidate in \
                    "/var/run/lightdm/root/$d" \
                    "/var/run/lightdm/root/:$D_NUM" \
                    "/run/lightdm/root/$d" \
                    "/run/lightdm/root/:$D_NUM" \
                    "/var/run/lightdm/authority/$D_NUM" \
                    "/run/lightdm/authority/$D_NUM" \
                    "/run/user/$SEAT_UID/.Xauthority" \
                    "/run/user/$SEAT_UID/gdm/Xauthority" \
                    "/run/user/$SEAT_UID/.mutter-Xwayland-Xauthority" \
                    "/home/$SEAT_USER/.Xauthority" \
                    "/tmp/.Xauthority-$SEAT_USER" \
                    "/tmp/.Xauthority-$D_NUM"; do
                    if [ -f "$candidate" ]; then D_XAUTH="$candidate"; break; fi
                done
            fi
            if [ -z "$D_XAUTH" ] && [ -n "$SEAT_UID" ]; then
                D_XAUTH=$(find /run/user/$SEAT_UID /home/$SEAT_USER /var/run/lightdm /run/lightdm -name "*$D_NUM*" -o -name "*Xauthority*" 2>/dev/null | head -n 1)
            fi
            [ -z "$D_XAUTH" ] && D_XAUTH="$XAUTHORITY"

            # C. Resolução de DBUS
            if [ -z "$SEAT_DBUS" ] && [ -n "$SEAT_UID" ] && [ -S "/run/user/$SEAT_UID/bus" ]; then
                SEAT_DBUS="unix:path=/run/user/$SEAT_UID/bus"
            fi

            # D. Permissão do display X11
            DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost + 2>/dev/null || true

            # E. Remove travas corrompidas de perfis do navegador
            if [ -n "$SEAT_USER" ] && [ -d "/home/$SEAT_USER" ]; then
                rm -f /home/$SEAT_USER/.mozilla/firefox/*/.parentlock 2>/dev/null || true
                rm -f /home/$SEAT_USER/.mozilla/firefox/*/lock 2>/dev/null || true
                rm -f /home/$SEAT_USER/.config/google-chrome/SingletonLock 2>/dev/null || true
                rm -f /home/$SEAT_USER/.config/chromium/SingletonLock 2>/dev/null || true
            fi

            # F. Execução do navegador no display e usuário alvo com fallback em cascata
            LAUNCH_CMD="
                if command -v google-chrome &>/dev/null; then
                    google-chrome --no-first-run --no-default-browser-check {safe_url}
                elif command -v firefox &>/dev/null; then
                    firefox --new-tab {safe_url} || firefox {safe_url}
                elif command -v chromium-browser &>/dev/null; then
                    chromium-browser --no-first-run {safe_url}
                elif command -v chromium &>/dev/null; then
                    chromium --no-first-run {safe_url}
                elif command -v xdg-open &>/dev/null; then
                    xdg-open {safe_url}
                fi
            "

            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ] && [ "$SEAT_USER" != "lightdm" ]; then
                sudo -u "$SEAT_USER" env DISPLAY="$d" XAUTHORITY="$D_XAUTH" DBUS_SESSION_BUS_ADDRESS="$SEAT_DBUS" nohup bash -c "$LAUNCH_CMD" </dev/null >/dev/null 2>&1 &
            else
                env DISPLAY="$d" XAUTHORITY="$D_XAUTH" DBUS_SESSION_BUS_ADDRESS="$SEAT_DBUS" nohup bash -c "$LAUNCH_CMD" </dev/null >/dev/null 2>&1 &
            fi

            LAUNCHED_COUNT=$((LAUNCHED_COUNT + 1))
        done

        echo "URL {safe_url} aberta com sucesso em $LAUNCHED_COUNT display(s)."
    """
    return X11_ENV_SETUP + core_logic, None

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
    command = r"""
        # Verifica se os comandos necessários existem para evitar erros.
        for cmd in top free df uptime; do
            if ! command -v $cmd &> /dev/null; then
                echo "Erro: O comando '$cmd' não foi encontrado na máquina remota." >&2
                exit 1
            fi
        done

        echo "---CPU_USAGE---"
        LC_ALL=C top -bn1 | grep 'Cpu(s)' | sed -E 's/.*, *([0-9.]+) id.*/\1/' | awk '{printf "%.1f%%", 100 - $1}'
        echo "----MEMORY----"
        LC_ALL=C free -h | grep '^Mem:' | awk '{print $3 "/" $2 " (Disp: " $7 ")"}'
        echo "----DISK----"
        LC_ALL=C df -h / | tail -n 1 | awk '{print $3 "/" $2 " (" $5 " uso)"}'
        echo "----UPTIME----"
        uptime -p
        echo "----REMOTE_TIME----"
        date +%s
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

@register_command('sync_time', 'Sincronizar Horário (NTP)', 'Gerenciamento do Sistema', icon='clock')
def _build_sync_time_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Força a sincronização do relógio do sistema via timedatectl."""
    return """
        echo "Sincronizando horário via NTP..."
        sudo timedatectl set-ntp false
        sudo timedatectl set-ntp true
        sleep 1
        echo "Status da sincronização:"
        timedatectl status | grep -E "synchronized|service"
        echo "Horário atual na máquina: $(date)"
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
    """Constrói um comando para mostrar/ocultar ícones do sistema para todos os usuários/sessões."""
    visibility_str = "true" if visible else "false"
    message = "ativados" if visible else "ocultados"
    return f"""
        SEEN_USERS=""
        PROCESSED_COUNT=0
        for U_DIR in /run/user/[1-9]* /home/*; do
            [ -e "$U_DIR" ] || continue
            U_BASE=$(basename "$U_DIR")
            if [[ "$U_BASE" =~ ^[0-9]+$ ]]; then
                U_UID="$U_BASE"
                U_NAME=$(getent passwd "$U_UID" 2>/dev/null | cut -d: -f1)
            else
                U_NAME="$U_BASE"
                U_UID=$(id -u "$U_NAME" 2>/dev/null)
            fi
            [ -z "$U_NAME" ] || [ "$U_NAME" = "root" ] || [ -z "$U_UID" ] || [ "$U_UID" -lt 1000 ] && continue
            if [[ " $SEEN_USERS " =~ " $U_NAME " ]]; then continue; fi
            SEEN_USERS="$SEEN_USERS $U_NAME"
            
            U_BUS="/run/user/$U_UID/bus"
            U_BUS_ARG=""
            [ -S "$U_BUS" ] && U_BUS_ARG="DBUS_SESSION_BUS_ADDRESS=unix:path=$U_BUS"
            U_DISP=$(ps -u "$U_NAME" -o args 2>/dev/null | grep -oP ':[0-9]+' | head -n 1)
            [ -z "$U_DISP" ] && U_DISP=":0"
            
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.nemo.desktop computer-icon-visible {visibility_str} 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.nemo.desktop home-icon-visible {visibility_str} 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.nemo.desktop trash-icon-visible {visibility_str} 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.nemo.desktop network-icon-visible {visibility_str} 2>/dev/null || true
            PROCESSED_COUNT=$((PROCESSED_COUNT + 1))
        done
        if [ "$PROCESSED_COUNT" -eq 0 ]; then
            gsettings set org.nemo.desktop computer-icon-visible {visibility_str} 2>/dev/null || true
            gsettings set org.nemo.desktop home-icon-visible {visibility_str} 2>/dev/null || true
            gsettings set org.nemo.desktop trash-icon-visible {visibility_str} 2>/dev/null || true
            gsettings set org.nemo.desktop network-icon-visible {visibility_str} 2>/dev/null || true
        fi
        echo "Ícones do sistema foram {message}."
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

def _build_get_default_browser_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Constrói um comando para consultar qual é o navegador padrão atual na máquina remota."""
    script = GSETTINGS_ENV_SETUP + r"""
        BROWSER_FILE=""
        if command -v xdg-settings &> /dev/null; then
            BROWSER_FILE=$(xdg-settings get default-web-browser 2>/dev/null)
        fi
        if [ -z "$BROWSER_FILE" ] && command -v xdg-mime &> /dev/null; then
            BROWSER_FILE=$(xdg-mime query default x-scheme-handler/http 2>/dev/null)
        fi
        if [ -z "$BROWSER_FILE" ] && command -v gio &> /dev/null; then
            BROWSER_FILE=$(gio mime x-scheme-handler/http 2>/dev/null | grep -oP '(?<=: ).*' | head -n 1)
        fi

        if [ -z "$BROWSER_FILE" ]; then
            echo "⚠️ Não foi possível determinar o navegador padrão (nenhuma associação encontrada)."
        else
            CLEAN_NAME=$(echo "$BROWSER_FILE" | sed -E 's/\.desktop$//i' | sed -E 's/-/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2); print $0}')
            echo "🌐 Navegador padrão atual: $CLEAN_NAME ($BROWSER_FILE)"
        fi
    """
    return script, None

def _build_panel_autohide_command(enable_autohide: bool) -> str:
    """Constrói um comando para ativar/desativar o auto-ocultar da barra de tarefas para todos os usuários/sessões."""
    autohide_str = "true" if enable_autohide else "false"
    message = "configurada para se ocultar automaticamente" if enable_autohide else "restaurada para o modo visível"
    return f"""
        SEEN_USERS=""
        PROCESSED_COUNT=0
        for U_DIR in /run/user/[1-9]* /home/*; do
            [ -e "$U_DIR" ] || continue
            U_BASE=$(basename "$U_DIR")
            if [[ "$U_BASE" =~ ^[0-9]+$ ]]; then
                U_UID="$U_BASE"
                U_NAME=$(getent passwd "$U_UID" 2>/dev/null | cut -d: -f1)
            else
                U_NAME="$U_BASE"
                U_UID=$(id -u "$U_NAME" 2>/dev/null)
            fi
            [ -z "$U_NAME" ] || [ "$U_NAME" = "root" ] || [ -z "$U_UID" ] || [ "$U_UID" -lt 1000 ] && continue
            if [[ " $SEEN_USERS " =~ " $U_NAME " ]]; then continue; fi
            SEEN_USERS="$SEEN_USERS $U_NAME"
            
            U_BUS="/run/user/$U_UID/bus"
            U_BUS_ARG=""
            [ -S "$U_BUS" ] && U_BUS_ARG="DBUS_SESSION_BUS_ADDRESS=unix:path=$U_BUS"
            U_DISP=$(ps -u "$U_NAME" -o args 2>/dev/null | grep -oP ':[0-9]+' | head -n 1)
            [ -z "$U_DISP" ] && U_DISP=":0"
            
            # 1. Configurar Cinnamon panels-autohide
            PANEL_IDS=$(sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings get org.cinnamon panels-enabled 2>/dev/null | grep -o -E "[0-9]+:[0-9]+:[a-zA-Z]+" | cut -d: -f1 | sort -u)
            if [ -z "$PANEL_IDS" ]; then
                PANEL_IDS="1 2"
            fi
            AUTOHIDE_LIST=""
            for id in $PANEL_IDS; do
                AUTOHIDE_LIST+="'$id:{autohide_str}',"
            done
            AUTOHIDE_LIST=${{AUTOHIDE_LIST%,}}
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon panels-autohide "[$AUTOHIDE_LIST]" 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon panels-hide-delay 0 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon panels-show-delay 100 2>/dev/null || true
            
            # 2. Configurar MATE panel se presente
            if command -v mate-panel >/dev/null 2>&1; then
                sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.mate.panel.toplevel:/org/mate/panel/toplevels/bottom/ auto-hide {autohide_str} 2>/dev/null || true
                sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.mate.panel.toplevel:/org/mate/panel/toplevels/top/ auto-hide {autohide_str} 2>/dev/null || true
            fi
            
            # 3. Configurar XFCE panel se presente
            if command -v xfconf-query >/dev/null 2>&1; then
                XFCE_AUTOHIDE_VAL={"1" if enable_autohide else "0"}
                sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" xfconf-query -c xfce4-panel -p /panels/panel-1/autohide-behavior -s "$XFCE_AUTOHIDE_VAL" 2>/dev/null || true
                sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" xfconf-query -c xfce4-panel -p /panels/panel-0/autohide-behavior -s "$XFCE_AUTOHIDE_VAL" 2>/dev/null || true
            fi
            PROCESSED_COUNT=$((PROCESSED_COUNT + 1))
        done
        
        if [ "$PROCESSED_COUNT" -eq 0 ]; then
            gsettings set org.cinnamon panels-autohide "['1:{autohide_str}', '2:{autohide_str}']" 2>/dev/null || true
        fi
        
        echo "Barra de tarefas {message}."
    """

def _build_panel_lock_command(lock: bool) -> str:
    """Constrói um comando para bloquear/desbloquear os applets da barra de tarefas para todos os usuários/sessões."""
    if lock:
        return """
        SEEN_USERS=""
        PROCESSED_COUNT=0
        for U_DIR in /run/user/[1-9]* /home/*; do
            [ -e "$U_DIR" ] || continue
            U_BASE=$(basename "$U_DIR")
            if [[ "$U_BASE" =~ ^[0-9]+$ ]]; then
                U_UID="$U_BASE"
                U_NAME=$(getent passwd "$U_UID" 2>/dev/null | cut -d: -f1)
            else
                U_NAME="$U_BASE"
                U_UID=$(id -u "$U_NAME" 2>/dev/null)
            fi
            [ -z "$U_NAME" ] || [ "$U_NAME" = "root" ] || [ -z "$U_UID" ] || [ "$U_UID" -lt 1000 ] && continue
            if [[ " $SEEN_USERS " =~ " $U_NAME " ]]; then continue; fi
            SEEN_USERS="$SEEN_USERS $U_NAME"
            
            U_BUS="/run/user/$U_UID/bus"
            U_BUS_ARG=""
            [ -S "$U_BUS" ] && U_BUS_ARG="DBUS_SESSION_BUS_ADDRESS=unix:path=$U_BUS"
            U_DISP=$(ps -u "$U_NAME" -o args 2>/dev/null | grep -oP ':[0-9]+' | head -n 1)
            [ -z "$U_DISP" ] && U_DISP=":0"
            
            U_HOME=$(getent passwd "$U_NAME" | cut -d: -f6)
            [ -z "$U_HOME" ] && U_HOME="/home/$U_NAME"
            BACKUP_FILE="$U_HOME/.applet_config_backup"
            
            CURRENT_APPLETS=$(sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings get org.cinnamon enabled-applets 2>/dev/null)
            if [ -n "$CURRENT_APPLETS" ] && [ "$CURRENT_APPLETS" != "@as []" ] && [ "$CURRENT_APPLETS" != "[]" ]; then
                echo "$CURRENT_APPLETS" > "$BACKUP_FILE"
                chown "$U_NAME:$U_NAME" "$BACKUP_FILE" 2>/dev/null || true
            fi
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon enabled-applets "[]" 2>/dev/null || true
            PROCESSED_COUNT=$((PROCESSED_COUNT + 1))
        done
        if [ "$PROCESSED_COUNT" -eq 0 ]; then
            gsettings get org.cinnamon enabled-applets > "$HOME/.applet_config_backup" 2>/dev/null || true
            gsettings set org.cinnamon enabled-applets "[]" 2>/dev/null || true
        fi
        echo "Barra de tarefas bloqueada (applets removidos)."
        """
    else:
        return """
        SEEN_USERS=""
        PROCESSED_COUNT=0
        for U_DIR in /run/user/[1-9]* /home/*; do
            [ -e "$U_DIR" ] || continue
            U_BASE=$(basename "$U_DIR")
            if [[ "$U_BASE" =~ ^[0-9]+$ ]]; then
                U_UID="$U_BASE"
                U_NAME=$(getent passwd "$U_UID" 2>/dev/null | cut -d: -f1)
            else
                U_NAME="$U_BASE"
                U_UID=$(id -u "$U_NAME" 2>/dev/null)
            fi
            [ -z "$U_NAME" ] || [ "$U_NAME" = "root" ] || [ -z "$U_UID" ] || [ "$U_UID" -lt 1000 ] && continue
            if [[ " $SEEN_USERS " =~ " $U_NAME " ]]; then continue; fi
            SEEN_USERS="$SEEN_USERS $U_NAME"
            
            U_BUS="/run/user/$U_UID/bus"
            U_BUS_ARG=""
            [ -S "$U_BUS" ] && U_BUS_ARG="DBUS_SESSION_BUS_ADDRESS=unix:path=$U_BUS"
            U_DISP=$(ps -u "$U_NAME" -o args 2>/dev/null | grep -oP ':[0-9]+' | head -n 1)
            [ -z "$U_DISP" ] && U_DISP=":0"
            
            U_HOME=$(getent passwd "$U_NAME" | cut -d: -f6)
            [ -z "$U_HOME" ] && U_HOME="/home/$U_NAME"
            BACKUP_FILE="$U_HOME/.applet_config_backup"
            
            if [ -f "$BACKUP_FILE" ]; then
                SAVED_APPLETS=$(cat "$BACKUP_FILE")
                if [ -n "$SAVED_APPLETS" ]; then
                    sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon enabled-applets "$SAVED_APPLETS" 2>/dev/null || true
                fi
                rm -f "$BACKUP_FILE"
            else
                sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings reset org.cinnamon enabled-applets 2>/dev/null || true
            fi
            PROCESSED_COUNT=$((PROCESSED_COUNT + 1))
        done
        if [ "$PROCESSED_COUNT" -eq 0 ]; then
            BACKUP_FILE="$HOME/.applet_config_backup"
            if [ -f "$BACKUP_FILE" ]; then
                gsettings set org.cinnamon enabled-applets "$(cat "$BACKUP_FILE")" 2>/dev/null || true
                rm -f "$BACKUP_FILE"
            else
                gsettings reset org.cinnamon enabled-applets 2>/dev/null || true
            fi
        fi
        echo "Barra de tarefas desbloqueada (applets restaurados)."
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
register_command('bloquear_barra_tarefas', 'Bloquear Barra de Tarefas', 'Controle da Interface', icon='lock', command_or_func=_build_panel_lock_command(True))
register_command('desbloquear_barra_tarefas', 'Desbloquear Barra de Tarefas', 'Controle da Interface', icon='unlock', command_or_func=_build_panel_lock_command(False))
register_command('obter_navegador_padrao', 'Verificar Navegador Padrão', 'Configurações do Navegador', icon='search', command_or_func=_build_get_default_browser_command)
register_command('definir_firefox_padrao', 'Firefox como Padrão', 'Configurações do Navegador', icon='globe', command_or_func=_build_xdg_default_browser_command('firefox.desktop'))
register_command('definir_chrome_padrao', 'Chrome como Padrão', 'Configurações do Navegador', icon='globe', command_or_func=_build_xdg_default_browser_command('google-chrome.desktop'))
register_command('desativar_perifericos', 'Desativar Mouse e Teclado', 'Controle de Periféricos', icon='mouse-pointer', command_or_func=_build_x_command_builder(MANAGE_PERIPHERALS_SCRIPT, 'disable', 'xinput'))
register_command('ativar_perifericos', 'Ativar Mouse e Teclado', 'Controle de Periféricos', icon='mouse-pointer', command_or_func=_build_x_command_builder(MANAGE_PERIPHERALS_SCRIPT, 'enable', 'xinput'))
register_command('desativar_botao_direito', 'Desativar Botão Direito', 'Controle de Periféricos', icon='slash', command_or_func=_build_x_command_builder(MANAGE_RIGHT_CLICK_SCRIPT, 'disable', 'xinput'))
@register_command('limpar_tela', 'Limpar Tela e Fechar Programas', 'Controle do Aluno', icon='trash-2')
def _build_limpar_tela_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Encerra os programas em execução do usuário e limpa o desktop.
    Suporta ambiente multiusuário e multiseat: limpa todas as sessões ativas de alunos.
    """
    target_user = data.get('target_user') or ''
    target_disp  = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''

    script = X11_ENV_SETUP + rf"""
        REQ_USER={safe_user}
        REQ_DISP={safe_disp}

        # 1. Fecha telas de aviso/bloqueio do próprio sistema (fullscreen_lock_overlay / zenity)
        pkill -f "fullscreen_lock_overlay.py" 2>/dev/null || true
        pkill -f "zenity --warning --title=TELA" 2>/dev/null || true
        pkill -f "pedir_silencio" 2>/dev/null || true

        # 2. Lista todos os usuários comuns (UID >= 1000) e usuários de GUI logados
        if [ -n "$REQ_USER" ]; then
            TARGET_USERS="$REQ_USER"
        else
            LOGGED_USERS=$(who 2>/dev/null | awk '{{print $1}}' | sort -u | tr '\n' ' ')
            PASSWD_USERS=$(awk -F: '$3 >= 1000 && $3 < 65000 {{print $1}}' /etc/passwd 2>/dev/null | tr '\n' ' ')
            TARGET_USERS=$(echo "$LOGGED_USERS $PASSWD_USERS aluno" | tr ' ' '\n' | sort -u | grep -v '^root$' | tr '\n' ' ')
        fi

        # 3. Lista todos os displays X11 ativos na máquina
        ALL_DISPLAYS=$(ls /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | tr '\n' ' ')
        [ -z "$ALL_DISPLAYS" ] && ALL_DISPLAYS=":0 :1 :2"
        [ -n "$REQ_DISP" ] && ALL_DISPLAYS="$REQ_DISP $ALL_DISPLAYS"

        # 4. Fecha janelas graciosamente em todos os displays X11 ativos usando wmctrl / xdotool
        for d in $ALL_DISPLAYS; do
            for u in $TARGET_USERS; do
                U_UID=$(id -u "$u" 2>/dev/null)
                U_XAUTH=""
                if [ -n "$U_UID" ]; then
                    for candidate in "/run/user/$U_UID/gdm/Xauthority" \
                                     "/run/user/$U_UID/.mutter-Xwayland-Xauthority" \
                                     "/run/user/$U_UID/.Xauthority" \
                                     "/var/run/lightdm/root/$d" \
                                     "/run/lightdm/root/$d" \
                                     "/home/$u/.Xauthority"; do
                        if [ -f "$candidate" ]; then U_XAUTH="$candidate"; break; fi
                    done
                fi
                [ -z "$U_XAUTH" ] && [ -f "/home/$u/.Xauthority" ] && U_XAUTH="/home/$u/.Xauthority"

                if command -v wmctrl &>/dev/null; then
                    sudo -u "$u" DISPLAY="$d" XAUTHORITY="${{U_XAUTH:-/home/$u/.Xauthority}}" wmctrl -l 2>/dev/null | awk '{{print $1}}' | while read win_id; do
                        sudo -u "$u" DISPLAY="$d" XAUTHORITY="${{U_XAUTH:-/home/$u/.Xauthority}}" wmctrl -ic "$win_id" 2>/dev/null || true
                    done
                fi
            done
        done

        sleep 0.3

        # 5. Lista completa de aplicativos de alunos para encerramento forçado (KILL)
        PROCS="chrome chromium chromium-browser google-chrome firefox firefox-esr msedge brave opera vivaldi epiphany \
               scratch scratch3 scratchjr scratch-desktop squeak idle idle3 thonny code vscodium geany gedit xed pluma kate mousepad \
               vlc mpv totem parole rhythmbox audacious soundconverter audacity \
               libreoffice soffice.bin soffice oosplash \
               gimp inkscape blender kcalc gnome-calculator galculator \
               gcompris gcompris-qt tuxpaint supertux supertuxkart minetest minecraft luanti openarena \
               gnome-mines gnome-sudoku quadrapassel swell-foop aisleriot sol \
               evince atril okular eog xviewer ristretto viewnior \
               gnome-terminal mate-terminal xfce4-terminal tilix alacritty kitty xterm rxvt"

        for proc in $PROCS; do
            pkill -9 -f "$proc" 2>/dev/null || true
        done

        # Encerra janelas avulsas de gerenciadores de arquivos sem matar a Área de Trabalho
        for u in $TARGET_USERS; do
            pkill -u "$u" -9 -f "nemo --no-desktop" 2>/dev/null || true
            pkill -u "$u" -9 -f "nautilus --no-desktop" 2>/dev/null || true
            pkill -u "$u" -9 -f "caja --no-desktop" 2>/dev/null || true
            pkill -u "$u" -9 -f "thunar" 2>/dev/null || true
        done

        # 6. Desloga usuários e limpa sessões/cookies/contas de todos os navegadores em todas as pastas /home/*
        for u in $TARGET_USERS; do
            USER_HOME=$(eval echo "~$u")
            if [ -d "$USER_HOME" ]; then
                # Google Chrome / Chromium / Edge / Brave
                for b_dir in "$USER_HOME/.config/google-chrome" \
                             "$USER_HOME/.config/chromium" \
                             "$USER_HOME/.config/microsoft-edge" \
                             "$USER_HOME/.config/BraveSoftware/Brave-Browser" \
                             "$USER_HOME/snap/chromium/common/.config/chromium"; do
                    if [ -d "$b_dir" ]; then
                        find "$b_dir" -type f \( \
                            -name "Cookies" -o -name "Cookies-journal" -o \
                            -name "Login Data" -o -name "Login Data-journal" -o \
                            -name "Web Data" -o -name "Web Data-journal" -o \
                            -name "Current Session" -o -name "Current Tabs" -o \
                            -name "Last Session" -o -name "Last Tabs" \
                        \) -delete 2>/dev/null || true

                        find "$b_dir" -type d \( \
                            -name "Sessions" -o \
                            -name "Session Storage" -o \
                            -name "Local Storage" -o \
                            -name "IndexedDB" -o \
                            -name "Service Worker" -o \
                            -name "Cache" -o \
                            -name "Code Cache" -o \
                            -name "GPUCache" \
                        \) -exec rm -rf {{}} + 2>/dev/null || true
                    fi
                done

                # Mozilla Firefox
                for f_dir in "$USER_HOME/.mozilla/firefox" \
                             "$USER_HOME/snap/firefox/common/.mozilla/firefox"; do
                    if [ -d "$f_dir" ]; then
                        find "$f_dir" -type f \( \
                            -name "cookies.sqlite*" -o \
                            -name "sessionstore.jsonlz4" -o \
                            -name "sessionstore.js" -o \
                            -name "logins.json" -o \
                            -name "key4.db" -o \
                            -name "formhistory.sqlite" -o \
                            -name "webappsstore.sqlite" \
                        \) -delete 2>/dev/null || true

                        find "$f_dir" -type d \( \
                            -name "sessionstore-backups" -o \
                            -name "storage" -o \
                            -name "cache2" \
                        \) -exec rm -rf {{}} + 2>/dev/null || true
                    fi
                done

                # Caches temporários dos navegadores em ~/.cache
                rm -rf "$USER_HOME/.cache/google-chrome" \
                       "$USER_HOME/.cache/chromium" \
                       "$USER_HOME/.cache/mozilla" \
                       "$USER_HOME/.cache/microsoft-edge" 2>/dev/null || true

                chown -R "$u:$u" "$USER_HOME/.config" "$USER_HOME/.mozilla" 2>/dev/null || true
            fi
        done

        # 7. Minimiza para Área de Trabalho limpa em todos os displays
        for d in $ALL_DISPLAYS; do
            for u in $TARGET_USERS; do
                if command -v xdotool &>/dev/null; then
                    U_XAUTH="/home/$u/.Xauthority"
                    sudo -u "$u" DISPLAY="$d" XAUTHORITY="$U_XAUTH" xdotool key super+d 2>/dev/null || true
                fi
            done
        done

        echo "Tela limpa com sucesso em todos os displays e usuários."
"""
    return script, None
    return script, None

@register_command('deslogar_navegadores', 'Deslogar Navegadores', 'Controle do Aluno', icon='log-out')
def _build_deslogar_navegadores_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Fecha os navegadores e limpa sessões, cookies, contas salvas e abas para a próxima turma."""
    target_user = data.get('target_user') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''

    script = X11_ENV_SETUP + rf"""
        REQ_USER={safe_user}
        if [ -n "$REQ_USER" ]; then
            GUI_USER="$REQ_USER"
        else
            GUI_USER=$(who 2>/dev/null | grep -E "(:[0-9]|\\btty[0-9]|\\bpts[0-9])" | awk '{{print $1}}' | head -n 1)
        fi
        [ -z "$GUI_USER" ] && GUI_USER="aluno"

        # 1. Encerra todos os processos de navegadores
        pkill -u "$GUI_USER" -9 -f "chrome|chromium|firefox|msedge|brave" 2>/dev/null || true
        sleep 0.3

        # 2. Limpa dados de autenticação, cookies e sessões de navegadores
        USER_HOME=$(eval echo "~$GUI_USER")
        if [ -d "$USER_HOME" ]; then
            for b_dir in "$USER_HOME/.config/google-chrome" \
                         "$USER_HOME/.config/chromium" \
                         "$USER_HOME/.config/microsoft-edge" \
                         "$USER_HOME/.config/BraveSoftware/Brave-Browser" \
                         "$USER_HOME/snap/chromium/common/.config/chromium"; do
                if [ -d "$b_dir" ]; then
                    find "$b_dir" -type f \( \
                        -name "Cookies" -o -name "Cookies-journal" -o \
                        -name "Login Data" -o -name "Login Data-journal" -o \
                        -name "Web Data" -o -name "Web Data-journal" -o \
                        -name "Current Session" -o -name "Current Tabs" -o \
                        -name "Last Session" -o -name "Last Tabs" \
                    \) -delete 2>/dev/null || true

                    find "$b_dir" -type d \( \
                        -name "Sessions" -o \
                        -name "Session Storage" -o \
                        -name "Local Storage" -o \
                        -name "IndexedDB" -o \
                        -name "Service Worker" -o \
                        -name "Cache" -o \
                        -name "Code Cache" -o \
                        -name "GPUCache" \
                    \) -exec rm -rf {{}} + 2>/dev/null || true
                fi
            done

            for f_dir in "$USER_HOME/.mozilla/firefox" \
                         "$USER_HOME/snap/firefox/common/.mozilla/firefox"; do
                if [ -d "$f_dir" ]; then
                    find "$f_dir" -type f \( \
                        -name "cookies.sqlite*" -o \
                        -name "sessionstore.jsonlz4" -o \
                        -name "sessionstore.js" -o \
                        -name "logins.json" -o \
                        -name "key4.db" -o \
                        -name "formhistory.sqlite" -o \
                        -name "webappsstore.sqlite" \
                    \) -delete 2>/dev/null || true

                    find "$f_dir" -type d \( \
                        -name "sessionstore-backups" -o \
                        -name "storage" -o \
                        -name "cache2" \
                    \) -exec rm -rf {{}} + 2>/dev/null || true
                fi
            done

            rm -rf "$USER_HOME/.cache/google-chrome" \
                   "$USER_HOME/.cache/chromium" \
                   "$USER_HOME/.cache/mozilla" \
                   "$USER_HOME/.cache/microsoft-edge" 2>/dev/null || true

            chown -R "$GUI_USER:$GUI_USER" "$USER_HOME/.config" "$USER_HOME/.mozilla" 2>/dev/null || true
        fi

        echo "Navegadores deslogados e sessões limpas para $GUI_USER."
"""
    return script, None

# RESTORE_PERIPHERALS_SH_SCRIPT e FULLSCREEN_LOCK_OVERLAY_PYTHON_SCRIPT carregados via scripts_client/

@register_command('bloquear_tela_mensagem', 'Bloquear Tela com Mensagem', 'Controle de Periféricos', icon='lock')
def _build_lock_screen_with_message(data: Dict[str, Any]) -> Tuple[str, None]:
    """Exibe um aviso em tela cheia e intercepta periféricos (teclado/mouse) aumentando 15 segundos a cada toque indevido."""
    raw_message = data.get('message') or data.get('lock_message') or 'Atenção ao Professor!'
    safe_msg = shlex.quote(str(raw_message).strip())
    
    raw_unlock_sec = data.get('unlock_seconds') or data.get('auto_unlock_sec') or 0
    if not raw_unlock_sec and data.get('auto_unlock_minutes'):
        try:
            raw_unlock_sec = int(data.get('auto_unlock_minutes')) * 60
        except Exception:
            raw_unlock_sec = 0
    safe_unlock_sec = shlex.quote(str(raw_unlock_sec))
    require_silence = "1" if (data.get('require_silence') or data.get('is_noise_lock')) else "0"
    safe_require_silence = shlex.quote(require_silence)

    target_user = data.get('target_user') or ''
    target_disp = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''

    script = X11_ENV_SETUP + f"""
        # Identificação precisa de usuário e display específico no ambiente Multiseat
        REQ_USER={safe_user}
        REQ_DISP={safe_disp}

        if [ -n "$REQ_USER" ]; then
            GUI_USER="$REQ_USER"
        else
            GUI_USER=$(who 2>/dev/null | grep -E "(:[0-9]|\\btty[0-9]|\\bpts[0-9])" | awk '{{print $1}}' | head -n 1)
        fi
        [ -z "$GUI_USER" ] && GUI_USER="aluno"
        GUI_UID=$(id -u "$GUI_USER" 2>/dev/null)

        # Descobre o DISPLAY específico da sessão deste usuário multiseat
        DISP=""
        if [ -n "$REQ_DISP" ]; then
            DISP="$REQ_DISP"
        elif [ -n "$GUI_UID" ]; then
            USER_PID=$(pgrep -u "$GUI_UID" -f "cinnamon-session|gnome-session|mate-session|xfce4-session|plasma|Xorg|Xwayland|mutter|kwin" 2>/dev/null | head -n 1)
            if [ -n "$USER_PID" ]; then
                DISP=$(awk -v RS='\\0' '/^DISPLAY=/ {{ sub(/^DISPLAY=/, ""); print }}' "/proc/$USER_PID/environ" 2>/dev/null)
            fi
        fi

        if [ -z "$DISP" ]; then
            WHO_DISP=$(who 2>/dev/null | grep "^$GUI_USER " | grep -o "(:[0-9.]*)" | tr -d "()" | head -n 1)
            [ -n "$WHO_DISP" ] && DISP="$WHO_DISP"
        fi

        if [ -z "$DISP" ]; then
            DISP=$(ls /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | head -n 1)
        fi
        [ -z "$DISP" ] && DISP=":0"

        # Descobre o XAUTHORITY específico da sessão deste usuário multiseat
        GUI_XAUTH=""
        if [ -n "$GUI_UID" ]; then
            for candidate in "/run/user/$GUI_UID/gdm/Xauthority" "/run/user/$GUI_UID/.mutter-Xwayland-Xauthority" "/run/user/$GUI_UID/.Xauthority" "/home/$GUI_USER/.Xauthority"; do
                if [ -f "$candidate" ]; then GUI_XAUTH="$candidate"; break; fi
            done
        fi
        [ -n "$GUI_XAUTH" ] && export XAUTHORITY="$GUI_XAUTH"
        export DISPLAY="$DISP"

        xhost +local: 2>/dev/null || xhost + 2>/dev/null || true

        pkill -f "fullscreen_lock_overlay.py" 2>/dev/null || true
        pkill -f "zenity --warning --title=TELA" 2>/dev/null || true
        

        cat <<'SH_EOF' > /tmp/restore_peripherals.sh
{RESTORE_PERIPHERALS_SH_SCRIPT}
SH_EOF
        chmod 777 /tmp/restore_peripherals.sh 2>/dev/null || true

        cat <<'EOF' > /tmp/fullscreen_lock_overlay.py
{FULLSCREEN_LOCK_OVERLAY_PYTHON_SCRIPT}
EOF
        chmod 777 /tmp/fullscreen_lock_overlay.py 2>/dev/null || true

        pkill -f "fullscreen_lock_overlay.py" 2>/dev/null || true
        rm -f /tmp/lock_noise_penalty /tmp/lock_calm_score /tmp/lock_calm_state /tmp/lock_individual_penalty /tmp/lock_calm_completed 2>/dev/null || true

        # 3. Descobrir todos os displays X11 ativos na máquina
        if [ -n "$REQ_DISP" ]; then
            DISPLAYS="$REQ_DISP"
        else
            DISPLAYS=$(ls -1 /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | sort -u)
            [ -z "$DISPLAYS" ] && DISPLAYS=":0"
        fi

        # 4. Bloquear e exibir overlay em todos os displays e sessões do Multiseat
        for d in $DISPLAYS; do
            D_NUM=$(echo "$d" | tr -d ':')

            SEAT_USER=""
            SEAT_UID=""
            SEAT_XAUTH=""
            SEAT_DBUS=""

            # A. Descobre via processos de sessão gráfica rodando neste display específico (/proc/*/environ)
            for pid in $(pgrep -f "cinnamon-session|gnome-session|xfce4-session|mate-session|lxsession|openbox|startplasma|plasma|Xorg|Xephyr|xinit|lightdm|gdm" 2>/dev/null); do
                [ ! -r "/proc/$pid/environ" ] && continue
                p_disp=$(awk -v RS='\\0' '/^DISPLAY=/ {{ sub(/^DISPLAY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                if [ "$p_disp" = "$d" ] || [ "$p_disp" = ":$D_NUM" ] || [ "$p_disp" = "$d.0" ]; then
                    p_u=$(awk -v RS='\\0' '/^USER=/ {{ sub(/^USER=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                    [ -z "$p_u" ] && p_u=$(ps -o user= -p "$pid" 2>/dev/null)
                    if [ -n "$p_u" ] && [ "$p_u" != "root" ] && [ "$p_u" != "lightdm" ] && [ "$p_u" != "gdm" ]; then
                        SEAT_USER="$p_u"
                        SEAT_UID=$(id -u "$p_u" 2>/dev/null)
                        SEAT_XAUTH=$(awk -v RS='\\0' '/^XAUTHORITY=/ {{ sub(/^XAUTHORITY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        SEAT_DBUS=$(awk -v RS='\\0' '/^DBUS_SESSION_BUS_ADDRESS=/ {{ sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        break
                    fi
                fi
            done

            # B. Se ainda não achou o usuário, busca via 'who' e sessões ativas
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | grep -E "(:$D_NUM\\b|\\($d\\))" | awk '{{print $1}}' | head -n 1)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(awk -F: -v uid="$((1000 + D_NUM))" '$3 == uid {{print $1}}' /etc/passwd 2>/dev/null)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | awk '{{print $1}}' | head -n 1)
            fi
            [ -z "$SEAT_USER" ] && SEAT_USER="aluno"
            [ -z "$SEAT_UID" ] && SEAT_UID=$(id -u "$SEAT_USER" 2>/dev/null)

            # Se a ação foi solicitada para um usuário específico, ignora outros displays
            if [ -n "$REQ_USER" ] && [ "$SEAT_USER" != "$REQ_USER" ]; then
                continue
            fi

            # C. Resolução completa e prioritária do XAUTHORITY para este display
            D_XAUTH=""
            if [ -n "$SEAT_XAUTH" ] && [ -f "$SEAT_XAUTH" ]; then
                D_XAUTH="$SEAT_XAUTH"
            fi

            if [ -z "$D_XAUTH" ]; then
                for candidate in \
                    "/var/run/lightdm/root/$d" \
                    "/var/run/lightdm/root/:$D_NUM" \
                    "/run/lightdm/root/$d" \
                    "/run/lightdm/root/:$D_NUM" \
                    "/var/run/lightdm/authority/$D_NUM" \
                    "/run/lightdm/authority/$D_NUM" \
                    "/run/user/$SEAT_UID/.Xauthority" \
                    "/run/user/$SEAT_UID/gdm/Xauthority" \
                    "/run/user/$SEAT_UID/.mutter-Xwayland-Xauthority" \
                    "/home/$SEAT_USER/.Xauthority" \
                    "/tmp/.Xauthority-$SEAT_USER" \
                    "/tmp/.Xauthority-$D_NUM"; do
                    if [ -f "$candidate" ]; then D_XAUTH="$candidate"; break; fi
                done
            fi

            if [ -z "$D_XAUTH" ] && [ -n "$SEAT_UID" ]; then
                D_XAUTH=$(find /run/user/$SEAT_UID /home/$SEAT_USER /var/run/lightdm /run/lightdm -name "*$D_NUM*" -o -name "*Xauthority*" 2>/dev/null | head -n 1)
            fi
            [ -z "$D_XAUTH" ] && D_XAUTH="$XAUTHORITY"
            [ -n "$D_XAUTH" ] && chmod 644 "$D_XAUTH" 2>/dev/null || true

            # D. Resolução de DBUS
            if [ -z "$SEAT_DBUS" ] && [ -n "$SEAT_UID" ] && [ -S "/run/user/$SEAT_UID/bus" ]; then
                SEAT_DBUS="unix:path=/run/user/$SEAT_UID/bus"
            fi

            # E. Libera acesso ao display local via xhost
            DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost + 2>/dev/null || true
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || true
            fi

            # F. Controle de periféricos: mantemos os periféricos ativos no X11 para que a janela de bloqueio capture as entradas e aplique a punição de +15s a cada toque
            DISPLAY="$d" XAUTHORITY="$D_XAUTH" /tmp/restore_peripherals.sh 2>/dev/null || true

            # G. Dispara tela de bloqueio no display (fecha avisos simples anteriores)
            pkill -9 -f "popup_message_overlay.py" 2>/dev/null || true
            pkill -9 -f "silence_alert_overlay.py" 2>/dev/null || true
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ] && [ "$SEAT_USER" != "lightdm" ]; then
                sudo -u "$SEAT_USER" env DISPLAY="$d" XAUTHORITY="$D_XAUTH" DBUS_SESSION_BUS_ADDRESS="$SEAT_DBUS" nohup python3 /tmp/fullscreen_lock_overlay.py {safe_msg} {safe_unlock_sec} {safe_require_silence} </dev/null >/tmp/fullscreen_lock_overlay.log 2>&1 &
            else
                nohup env DISPLAY="$d" XAUTHORITY="$D_XAUTH" DBUS_SESSION_BUS_ADDRESS="$SEAT_DBUS" python3 /tmp/fullscreen_lock_overlay.py {safe_msg} {safe_unlock_sec} {safe_require_silence} </dev/null >/tmp/fullscreen_lock_overlay.log 2>&1 &
            fi
        done

        echo "Aviso de bloqueio de tela iniciado com sucesso em todas as sessões multiseat."
        exit 0
    """
    return script, None

@register_command('desbloquear_tela_mensagem', 'Desbloquear Tela', 'Controle de Periféricos', icon='unlock')
def _build_unlock_screen_with_message(data: Dict[str, Any]) -> Tuple[str, None]:
    """Encerra o aviso em tela cheia e reativa os periféricos."""
    target_user = data.get('target_user') or ''
    target_disp = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''
    force_unlock = "1" if (data.get('force') or data.get('force_unlock')) else "0"
    safe_force = shlex.quote(force_unlock)

    script = X11_ENV_SETUP + f"""
        REQ_USER={safe_user}
        REQ_DISP={safe_disp}
        FORCE_UNLOCK={safe_force}

        # Se for um término automático coletivo (sem força manual do professor)
        # e o aluno ainda tiver uma punição individual ativa por toques,
        # não matamos o overlay: sinalizamos a meta de 100% para a máquina e mantemos a punição rodando
        if [ "$FORCE_UNLOCK" != "1" ] && [ -f /tmp/lock_individual_penalty ]; then
            echo "100" > /tmp/lock_calm_score 2>/dev/null || true
            touch /tmp/lock_calm_completed 2>/dev/null || true
            echo "Aviso: A sala atingiu a meta de 100%, mas este computador possui punição individual pendente. Mantendo tela bloqueada até o término da contagem."
            exit 0
        fi

        rm -f /tmp/lock_individual_penalty /tmp/lock_calm_completed /tmp/lock_overlay_active /tmp/lock_noise_penalty /tmp/lock_calm_score /tmp/lock_calm_state 2>/dev/null || true
        pkill -f "fullscreen_lock_overlay.py" 2>/dev/null || true
        pkill -f "zenity --warning --title=TELA" 2>/dev/null || true
        pkill -f "xmessage" 2>/dev/null || true
        
        # 1. Acorda os dispositivos USB HID e desativa economia/autosuspend no kernel
        if [ -d /sys/bus/usb/devices ]; then
            for f in /sys/bus/usb/devices/*/power/control; do [ -w "$f" ] && echo on > "$f" 2>/dev/null || true; done
            for f in /sys/bus/usb/devices/*/power/autosuspend; do [ -w "$f" ] && echo -1 > "$f" 2>/dev/null || true; done
        fi
        udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true
        udevadm trigger --subsystem-match=hid --action=change 2>/dev/null || true

        # 2. Descobrir todos os displays X11 ativos na máquina
        if [ -n "$REQ_DISP" ]; then
            DISPLAYS="$REQ_DISP"
        else
            DISPLAYS=$(ls -1 /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | sort -u)
            [ -z "$DISPLAYS" ] && DISPLAYS=":0"
        fi

        for d in $DISPLAYS; do
            D_NUM=$(echo "$d" | tr -d ':')

            SEAT_USER=""
            SEAT_UID=""
            SEAT_XAUTH=""
            SEAT_DBUS=""

            # A. Descobre via processos de sessão gráfica rodando neste display específico (/proc/*/environ)
            for pid in $(pgrep -f "cinnamon-session|gnome-session|xfce4-session|mate-session|lxsession|openbox|startplasma|plasma|Xorg|Xephyr|xinit|lightdm|gdm" 2>/dev/null); do
                [ ! -r "/proc/$pid/environ" ] && continue
                p_disp=$(awk -v RS='\\0' '/^DISPLAY=/ {{ sub(/^DISPLAY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                if [ "$p_disp" = "$d" ] || [ "$p_disp" = ":$D_NUM" ] || [ "$p_disp" = "$d.0" ]; then
                    p_u=$(awk -v RS='\\0' '/^USER=/ {{ sub(/^USER=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                    [ -z "$p_u" ] && p_u=$(ps -o user= -p "$pid" 2>/dev/null)
                    if [ -n "$p_u" ] && [ "$p_u" != "root" ] && [ "$p_u" != "lightdm" ] && [ "$p_u" != "gdm" ]; then
                        SEAT_USER="$p_u"
                        SEAT_UID=$(id -u "$p_u" 2>/dev/null)
                        SEAT_XAUTH=$(awk -v RS='\\0' '/^XAUTHORITY=/ {{ sub(/^XAUTHORITY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        SEAT_DBUS=$(awk -v RS='\\0' '/^DBUS_SESSION_BUS_ADDRESS=/ {{ sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        break
                    fi
                fi
            done

            # B. Se ainda não achou o usuário, busca via 'who' e sessões ativas
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | grep -E "(:$D_NUM\\b|\\($d\\))" | awk '{{print $1}}' | head -n 1)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(awk -F: -v uid="$((1000 + D_NUM))" '$3 == uid {{print $1}}' /etc/passwd 2>/dev/null)
            fi
            if [ -z "$SEAT_USER" ]; then
                SEAT_USER=$(who 2>/dev/null | awk '{{print $1}}' | head -n 1)
            fi
            [ -z "$SEAT_USER" ] && SEAT_USER="aluno"
            [ -z "$SEAT_UID" ] && SEAT_UID=$(id -u "$SEAT_USER" 2>/dev/null)

            # Se a ação foi solicitada para um usuário específico, ignora outros displays
            if [ -n "$REQ_USER" ] && [ "$SEAT_USER" != "$REQ_USER" ]; then
                continue
            fi

            # C. Resolução completa e prioritária do XAUTHORITY para este display
            D_XAUTH=""
            if [ -n "$SEAT_XAUTH" ] && [ -f "$SEAT_XAUTH" ]; then
                D_XAUTH="$SEAT_XAUTH"
            fi

            if [ -z "$D_XAUTH" ]; then
                for candidate in \
                    "/var/run/lightdm/root/$d" \
                    "/var/run/lightdm/root/:$D_NUM" \
                    "/run/lightdm/root/$d" \
                    "/run/lightdm/root/:$D_NUM" \
                    "/var/run/lightdm/authority/$D_NUM" \
                    "/run/lightdm/authority/$D_NUM" \
                    "/run/user/$SEAT_UID/.Xauthority" \
                    "/run/user/$SEAT_UID/gdm/Xauthority" \
                    "/run/user/$SEAT_UID/.mutter-Xwayland-Xauthority" \
                    "/home/$SEAT_USER/.Xauthority" \
                    "/tmp/.Xauthority-$SEAT_USER" \
                    "/tmp/.Xauthority-$D_NUM"; do
                    if [ -f "$candidate" ]; then D_XAUTH="$candidate"; break; fi
                done
            fi

            if [ -z "$D_XAUTH" ] && [ -n "$SEAT_UID" ]; then
                D_XAUTH=$(find /run/user/$SEAT_UID /home/$SEAT_USER /var/run/lightdm /run/lightdm -name "*$D_NUM*" -o -name "*Xauthority*" 2>/dev/null | head -n 1)
            fi
            [ -z "$D_XAUTH" ] && D_XAUTH="$XAUTHORITY"

            # D. Resolução de DBUS
            if [ -z "$SEAT_DBUS" ] && [ -n "$SEAT_UID" ] && [ -S "/run/user/$SEAT_UID/bus" ]; then
                SEAT_DBUS="unix:path=/run/user/$SEAT_UID/bus"
            fi

            # E. Libera acesso ao display local via xhost
            DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost + 2>/dev/null || true
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || true
            fi

            # F. Reativa teclado e mouse no X11
            if command -v xinput &> /dev/null; then
                MASTER_KBD=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/Virtual core keyboard|master keyboard/ {{for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {{split($i,a,"="); print a[2]}}}}' | head -n 1)
                [ -z "$MASTER_KBD" ] && MASTER_KBD=3

                MASTER_PTR=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/Virtual core pointer|master pointer/ {{for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {{split($i,a,"="); print a[2]}}}}' | head -n 1)
                [ -z "$MASTER_PTR" ] && MASTER_PTR=2

                MASTER_IDS=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list 2>/dev/null | awk '/master/ {{ for (i=1; i<=NF; i++) if ($i ~ /^id=[0-9]+$/) {{ split($i, a, "="); print a[2]; }} }}')
                for m_id in $MASTER_IDS; do
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput enable "$m_id" 2>/dev/null || true
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput set-prop "$m_id" "Device Enabled" 1 2>/dev/null || true
                    if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                        sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput enable "$m_id" 2>/dev/null || true
                        sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput set-prop "$m_id" "Device Enabled" 1 2>/dev/null || true
                    fi
                done

                ALL_IDS=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list --id-only 2>/dev/null || true)
                for id in $ALL_IDS; do
                    DEV_NAME=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list --name-only "$id" 2>/dev/null || true)
                    if echo "$DEV_NAME" | grep -qi "XTEST"; then
                        continue
                    fi
                    if echo " $MASTER_IDS " | grep -q " $id "; then
                        continue
                    fi

                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput enable "$id" 2>/dev/null || true
                    DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput set-prop "$id" "Device Enabled" 1 2>/dev/null || true
                    if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                        sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput enable "$id" 2>/dev/null || true
                        sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput set-prop "$id" "Device Enabled" 1 2>/dev/null || true
                    fi

                    DEV_INFO=$(DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput list "$id" 2>/dev/null || true)
                    if echo "$DEV_INFO" | grep -qi "KeyClass" || echo "$DEV_NAME" | grep -qi -E "keyboard|key|kbd"; then
                        DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput reattach "$id" "$MASTER_KBD" 2>/dev/null || true
                        if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                            sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput reattach "$id" "$MASTER_KBD" 2>/dev/null || true
                        fi
                    fi
                    if echo "$DEV_INFO" | grep -qi -E "ButtonClass|ValuatorClass" || echo "$DEV_NAME" | grep -qi -E "mouse|pointer|touchpad|trackpoint|touchscreen"; then
                        DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput reattach "$id" "$MASTER_PTR" 2>/dev/null || true
                        if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                            sudo -u "$SEAT_USER" DISPLAY="$d" XAUTHORITY="$D_XAUTH" xinput reattach "$id" "$MASTER_PTR" 2>/dev/null || true
                        fi
                    fi
                done
                
                DISPLAY="$d" XAUTHORITY="$D_XAUTH" setxkbmap br 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" setxkbmap us 2>/dev/null || true
            fi
        done
        
        rm -f /tmp/fullscreen_lock_overlay.py 2>/dev/null || true
        echo "Tela desbloqueada com sucesso em todas as sessões multiseat."
        exit 0
    """
    return script, None

@register_command('semaforo_ruido', 'Semáforo de Ruído no Monitor do Aluno', 'Controle da Interface', icon='activity')
def _build_semaforo_ruido_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Exibe ou atualiza o widget do Semáforo Pedagógico de Ruído nos monitores dos alunos."""
    level = str(data.get('level', 'green')).lower().strip()
    db_val = float(data.get('db', 60.0))
    threshold = int(data.get('threshold', 75))
    target_user = data.get('target_user') or ''
    target_disp = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''

    if level in ('off', 'fechar', 'desativar', 'hide'):
        script = X11_ENV_SETUP + """
            pkill -9 -f "semaforo_overlay.py" 2>/dev/null || true
            rm -f /tmp/semaforo_overlay.py /tmp/semaforo_state.json 2>/dev/null || true
            echo "Semáforo de ruído desativado nas telas dos alunos."
            exit 0
        """
        return script, None

    safe_level = shlex.quote(level)
    safe_db = shlex.quote(str(round(db_val, 1)))
    safe_thresh = shlex.quote(str(threshold))

    script = X11_ENV_SETUP + f"""
        REQ_USER={safe_user}
        REQ_DISP={safe_disp}

        cat <<'EOF_SEMAFORO' > /tmp/semaforo_overlay.py
{SEMAFORO_OVERLAY_SCRIPT.strip()}
EOF_SEMAFORO

        chmod 777 /tmp/semaforo_overlay.py 2>/dev/null || chmod +x /tmp/semaforo_overlay.py
        pkill -9 -f "semaforo_overlay.py" 2>/dev/null || true

        if [ -n "$REQ_DISP" ]; then
            DISPLAYS="$REQ_DISP"
        else
            DISPLAYS=$(ls -1 /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | sort -u)
            [ -z "$DISPLAYS" ] && DISPLAYS=":0"
        fi

        for d in $DISPLAYS; do
            D_NUM=$(echo "$d" | tr -d ':')
            SEAT_USER=""
            SEAT_UID=""
            SEAT_XAUTH=""
            SEAT_DBUS=""

            for pid in $(pgrep -f "cinnamon-session|gnome-session|xfce4-session|mate-session|lxsession|openbox|startplasma|plasma|Xorg|Xephyr|xinit|lightdm|gdm" 2>/dev/null); do
                [ ! -r "/proc/$pid/environ" ] && continue
                p_disp=$(awk -v RS='\\0' '/^DISPLAY=/ {{ sub(/^DISPLAY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                if [ "$p_disp" = "$d" ] || [ "$p_disp" = ":$D_NUM" ] || [ "$p_disp" = "$d.0" ]; then
                    p_u=$(awk -v RS='\\0' '/^USER=/ {{ sub(/^USER=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                    [ -z "$p_u" ] && p_u=$(ps -o user= -p "$pid" 2>/dev/null)
                    if [ -n "$p_u" ] && [ "$p_u" != "root" ] && [ "$p_u" != "lightdm" ] && [ "$p_u" != "gdm" ]; then
                        SEAT_USER="$p_u"
                        SEAT_UID=$(id -u "$p_u" 2>/dev/null)
                        SEAT_XAUTH=$(awk -v RS='\\0' '/^XAUTHORITY=/ {{ sub(/^XAUTHORITY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        SEAT_DBUS=$(awk -v RS='\\0' '/^DBUS_SESSION_BUS_ADDRESS=/ {{ sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        break
                    fi
                fi
            done

            [ -z "$SEAT_USER" ] && SEAT_USER=$(who 2>/dev/null | grep -E "(:$D_NUM\\b|\\($d\\))" | awk '{{print $1}}' | head -n 1)
            [ -z "$SEAT_USER" ] && SEAT_USER="aluno"
            [ -z "$SEAT_UID" ] && SEAT_UID=$(id -u "$SEAT_USER" 2>/dev/null)

            if [ -n "$REQ_USER" ] && [ "$SEAT_USER" != "$REQ_USER" ]; then
                continue
            fi

            D_XAUTH="$SEAT_XAUTH"
            if [ -z "$D_XAUTH" ]; then
                for candidate in "/var/run/lightdm/root/$d" "/run/lightdm/root/$d" "/run/user/$SEAT_UID/.Xauthority" "/run/user/$SEAT_UID/gdm/Xauthority" "/home/$SEAT_USER/.Xauthority"; do
                    if [ -f "$candidate" ]; then D_XAUTH="$candidate"; break; fi
                done
            fi
            [ -z "$D_XAUTH" ] && D_XAUTH="$XAUTHORITY"

            DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost + 2>/dev/null || true
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                sudo -u "$SEAT_USER" env DISPLAY="$d" XAUTHORITY="$D_XAUTH" nohup python3 /tmp/semaforo_overlay.py {safe_level} {safe_db} {safe_thresh} </dev/null >/dev/null 2>&1 &
            else
                nohup env DISPLAY="$d" XAUTHORITY="$D_XAUTH" python3 /tmp/semaforo_overlay.py {safe_level} {safe_db} {safe_thresh} </dev/null >/dev/null 2>&1 &
            fi
        done

        echo "Semáforo de ruído sincronizado nas telas dos alunos."
        exit 0
    """
    return script, None

@register_command('celebrar_turma_nota_10', 'Celebração Turma Nota 10', 'Ações Remotas', icon='award')
def _build_celebrar_turma_nota_10_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Exibe tela festiva de premiação pedagógica e comemoração 'Turma Nota 10'."""
    stars = int(data.get('stars', 3))
    period_name = str(data.get('period_name', 'Aula')).strip()
    custom_msg = str(data.get('message', 'Parabéns a toda a turma pela dedicação e excelente disciplina!')).strip()
    target_user = data.get('target_user') or ''
    target_disp = data.get('display') or data.get('target_display') or ''
    safe_user = shlex.quote(str(target_user).strip()) if target_user else ''
    safe_disp = shlex.quote(str(target_disp).strip()) if target_disp else ''

    safe_stars = shlex.quote(str(stars))
    safe_period = shlex.quote(period_name)
    safe_msg = shlex.quote(custom_msg)

    script = X11_ENV_SETUP + f"""
        REQ_USER={safe_user}
        REQ_DISP={safe_disp}

        cat <<'EOF_CELEBRAR' > /tmp/celebrar_overlay.py
{CELEBRAR_OVERLAY_SCRIPT.strip()}
EOF_CELEBRAR

        chmod 777 /tmp/celebrar_overlay.py 2>/dev/null || chmod +x /tmp/celebrar_overlay.py
        pkill -9 -f "celebrar_overlay.py" 2>/dev/null || true

        if [ -n "$REQ_DISP" ]; then
            DISPLAYS="$REQ_DISP"
        else
            DISPLAYS=$(ls -1 /tmp/.X11-unix/X* 2>/dev/null | sed 's|/tmp/.X11-unix/X|:|' | sort -u)
            [ -z "$DISPLAYS" ] && DISPLAYS=":0"
        fi

        for d in $DISPLAYS; do
            D_NUM=$(echo "$d" | tr -d ':')
            SEAT_USER=""
            SEAT_UID=""
            SEAT_XAUTH=""
            SEAT_DBUS=""

            for pid in $(pgrep -f "cinnamon-session|gnome-session|xfce4-session|mate-session|lxsession|openbox|startplasma|plasma|Xorg|Xephyr|xinit|lightdm|gdm" 2>/dev/null); do
                [ ! -r "/proc/$pid/environ" ] && continue
                p_disp=$(awk -v RS='\\0' '/^DISPLAY=/ {{ sub(/^DISPLAY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                if [ "$p_disp" = "$d" ] || [ "$p_disp" = ":$D_NUM" ] || [ "$p_disp" = "$d.0" ]; then
                    p_u=$(awk -v RS='\\0' '/^USER=/ {{ sub(/^USER=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                    [ -z "$p_u" ] && p_u=$(ps -o user= -p "$pid" 2>/dev/null)
                    if [ -n "$p_u" ] && [ "$p_u" != "root" ] && [ "$p_u" != "lightdm" ] && [ "$p_u" != "gdm" ]; then
                        SEAT_USER="$p_u"
                        SEAT_UID=$(id -u "$p_u" 2>/dev/null)
                        SEAT_XAUTH=$(awk -v RS='\\0' '/^XAUTHORITY=/ {{ sub(/^XAUTHORITY=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        SEAT_DBUS=$(awk -v RS='\\0' '/^DBUS_SESSION_BUS_ADDRESS=/ {{ sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }}' "/proc/$pid/environ" 2>/dev/null)
                        break
                    fi
                fi
            done

            [ -z "$SEAT_USER" ] && SEAT_USER=$(who 2>/dev/null | grep -E "(:$D_NUM\\b|\\($d\\))" | awk '{{print $1}}' | head -n 1)
            [ -z "$SEAT_USER" ] && SEAT_USER="aluno"
            [ -z "$SEAT_UID" ] && SEAT_UID=$(id -u "$SEAT_USER" 2>/dev/null)

            if [ -n "$REQ_USER" ] && [ "$SEAT_USER" != "$REQ_USER" ]; then
                continue
            fi

            D_XAUTH="$SEAT_XAUTH"
            if [ -z "$D_XAUTH" ]; then
                for candidate in "/var/run/lightdm/root/$d" "/run/lightdm/root/$d" "/run/user/$SEAT_UID/.Xauthority" "/run/user/$SEAT_UID/gdm/Xauthority" "/home/$SEAT_USER/.Xauthority"; do
                    if [ -f "$candidate" ]; then D_XAUTH="$candidate"; break; fi
                done
            fi
            [ -z "$D_XAUTH" ] && D_XAUTH="$XAUTHORITY"

            DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost +local: 2>/dev/null || DISPLAY="$d" XAUTHORITY="$D_XAUTH" xhost + 2>/dev/null || true
            if [ -n "$SEAT_USER" ] && [ "$SEAT_USER" != "root" ]; then
                sudo -u "$SEAT_USER" env DISPLAY="$d" XAUTHORITY="$D_XAUTH" nohup python3 /tmp/celebrar_overlay.py {safe_stars} {safe_period} {safe_msg} </dev/null >/dev/null 2>&1 &
            else
                nohup env DISPLAY="$d" XAUTHORITY="$D_XAUTH" python3 /tmp/celebrar_overlay.py {safe_stars} {safe_period} {safe_msg} </dev/null >/dev/null 2>&1 &
            fi
        done

        echo "Celebração Turma Nota 10 exibida nas telas dos alunos."
        exit 0
    """
    return script, None

@register_command('iniciar_modo_demo', 'Iniciar Modo Demonstração / Transmissão da Tela', 'Controle da Interface', icon='tv')
def _build_start_demo_mode(data: Dict[str, Any]) -> Tuple[str, None]:
    """Inicia o modo demonstração transmitindo a tela do professor em Modo Kiosk."""
    professor_ip = data.get('professor_ip') or data.get('server_ip') or '192.168.50.209'
    target_url = data.get('url') or f"http://{professor_ip}:5950/"
    safe_url = shlex.quote(target_url)
    disp = str(data.get('display') or data.get('target_display') or ':0').strip()
    disp_export = f'export DISPLAY="{disp}"\n' if disp and disp.startswith(':') else 'export DISPLAY=":0"\n'
    
    script = X11_ENV_SETUP + f"""
{disp_export}
USER_NAME=$(who | grep -E ":0|tty[0-9]|pts[0-9]" | awk '{{print $1}}' | head -n 1)
[ -z "$USER_NAME" ] && USER_NAME="aluno"

pkill -u "$USER_NAME" -f "modo_demo_chrome" 2>/dev/null || true
pkill -u "$USER_NAME" -f "google-chrome --kiosk" 2>/dev/null || true
pkill -u "$USER_NAME" -f "chromium-browser --kiosk" 2>/dev/null || true
pkill -u "$USER_NAME" -f "firefox --kiosk" 2>/dev/null || true

if command -v google-chrome >/dev/null 2>&1; then
    sudo -u "$USER_NAME" DISPLAY="$DISPLAY" nohup google-chrome --kiosk --no-first-run --no-default-browser-check {safe_url} --user-data-dir=/tmp/modo_demo_chrome >/dev/null 2>&1 &
elif command -v chromium-browser >/dev/null 2>&1; then
    sudo -u "$USER_NAME" DISPLAY="$DISPLAY" nohup chromium-browser --kiosk --no-first-run --no-default-browser-check {safe_url} --user-data-dir=/tmp/modo_demo_chrome >/dev/null 2>&1 &
elif command -v firefox >/dev/null 2>&1; then
    sudo -u "$USER_NAME" DISPLAY="$DISPLAY" nohup firefox --kiosk {safe_url} >/dev/null 2>&1 &
else
    echo "Nenhum navegador compatível encontrado para o Modo Aula." >&2
    exit 1
fi
echo "Transmissão da tela do professor iniciada em $USER_NAME."
"""
    return script, None

@register_command('parar_modo_demo', 'Parar Modo Demonstração / Transmissão', 'Controle da Interface', icon='stop-circle')
def _build_stop_demo_mode(data: Dict[str, Any]) -> Tuple[str, None]:
    """Encerra o modo demonstração nas máquinas remotas."""
    disp = str(data.get('display') or data.get('target_display') or ':0').strip()
    disp_export = f'export DISPLAY="{disp}"\n' if disp and disp.startswith(':') else 'export DISPLAY=":0"\n'
    
    script = X11_ENV_SETUP + f"""
{disp_export}
USER_NAME=$(who | grep -E ":0|tty[0-9]|pts[0-9]" | awk '{{print $1}}' | head -n 1)
[ -z "$USER_NAME" ] && USER_NAME="aluno"

pkill -u "$USER_NAME" -f "modo_demo_chrome" 2>/dev/null || true
pkill -u "$USER_NAME" -f "google-chrome --kiosk" 2>/dev/null || true
pkill -u "$USER_NAME" -f "chromium-browser --kiosk" 2>/dev/null || true
pkill -u "$USER_NAME" -f "firefox --kiosk" 2>/dev/null || true
echo "Transmissão da tela do professor encerrada para $USER_NAME."
"""
    return script, None



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
    """Bloqueia a execução do terminal, fecha instâncias ativas e remove permissão dos executáveis."""
    script = GSETTINGS_ENV_SETUP + r"""
        echo "Aplicando bloqueio de terminal..."
        
        # 1. Configurações de lockdown e atalhos via gsettings
        gsettings set org.cinnamon.desktop.lockdown disable-command-line true 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.terminal "[]" 2>/dev/null || true
        gsettings set org.gnome.desktop.lockdown disable-command-line true 2>/dev/null || true
        gsettings set org.mate.lockdown disable-command-line true 2>/dev/null || true

        # 2. Fechar todos os terminais abertos imediatamente
        TERM_PROCESSES="gnome-terminal|gnome-terminal-server|mate-terminal|xfce4-terminal|xterm|uxterm|tilix|konsole|alacritty|kitty|lxterminal|terminator|qterminal|deepin-terminal"
        sudo pkill -9 -f "$TERM_PROCESSES" 2>/dev/null || true

        # 3. Restringir permissões de execução dos binários para apenas o root (chmod 700)
        TERM_BINS=(
            "/usr/bin/gnome-terminal"
            "/usr/bin/gnome-terminal.real"
            "/usr/bin/gnome-terminal.wrapper"
            "/usr/libexec/gnome-terminal-server"
            "/usr/lib/gnome-terminal/gnome-terminal-server"
            "/usr/bin/mate-terminal"
            "/usr/bin/xfce4-terminal"
            "/usr/bin/xterm"
            "/usr/bin/uxterm"
            "/usr/bin/lxterminal"
            "/usr/bin/tilix"
            "/usr/bin/terminator"
            "/usr/bin/konsole"
            "/usr/bin/alacritty"
            "/usr/bin/kitty"
            "/usr/bin/qterminal"
            "/usr/bin/deepin-terminal"
            "/usr/bin/x-terminal-emulator"
        )
        for bin_path in "${TERM_BINS[@]}"; do
            if [ -e "$bin_path" ]; then
                REAL_TARGET=$(realpath "$bin_path" 2>/dev/null || echo "$bin_path")
                sudo chmod 700 "$bin_path" 2>/dev/null || true
                if [ -n "$REAL_TARGET" ] && [ -e "$REAL_TARGET" ]; then
                    sudo chmod 700 "$REAL_TARGET" 2>/dev/null || true
                fi
            fi
        done

        echo "Acesso ao terminal e linha de comando bloqueado com sucesso."
    """
    return script.strip(), None

@register_command('desbloquear_terminal', 'Desbloquear Terminal', 'Controle da Interface', icon='terminal')
def _build_unblock_terminal_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Restaura o acesso ao terminal e as permissões de execução dos binários."""
    script = GSETTINGS_ENV_SETUP + r"""
        echo "Restaurando acesso ao terminal..."

        # 1. Restaurar permissões dos binários de terminal (chmod 755)
        TERM_BINS=(
            "/usr/bin/gnome-terminal"
            "/usr/bin/gnome-terminal.real"
            "/usr/bin/gnome-terminal.wrapper"
            "/usr/libexec/gnome-terminal-server"
            "/usr/lib/gnome-terminal/gnome-terminal-server"
            "/usr/bin/mate-terminal"
            "/usr/bin/xfce4-terminal"
            "/usr/bin/xterm"
            "/usr/bin/uxterm"
            "/usr/bin/lxterminal"
            "/usr/bin/tilix"
            "/usr/bin/terminator"
            "/usr/bin/konsole"
            "/usr/bin/alacritty"
            "/usr/bin/kitty"
            "/usr/bin/qterminal"
            "/usr/bin/deepin-terminal"
            "/usr/bin/x-terminal-emulator"
        )
        for bin_path in "${TERM_BINS[@]}"; do
            if [ -e "$bin_path" ]; then
                REAL_TARGET=$(realpath "$bin_path" 2>/dev/null || echo "$bin_path")
                sudo chmod 755 "$bin_path" 2>/dev/null || true
                if [ -n "$REAL_TARGET" ] && [ -e "$REAL_TARGET" ]; then
                    sudo chmod 755 "$REAL_TARGET" 2>/dev/null || true
                fi
            fi
        done

        # 2. Restaurar atalhos e configurações de lockdown
        gsettings set org.cinnamon.desktop.lockdown disable-command-line false 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.terminal "['<Primary><Alt>t']" 2>/dev/null || true
        gsettings set org.gnome.desktop.lockdown disable-command-line false 2>/dev/null || true
        gsettings set org.mate.lockdown disable-command-line false 2>/dev/null || true

        echo "Acesso ao terminal restaurado com sucesso."
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

@register_command('bloquear_combinacoes_teclas', 'Bloquear Combinações de Teclas', 'Controle da Interface', icon='lock')
def _build_lock_keybindings_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Bloqueia todas as combinações de teclas do sistema no Linux Mint Cinnamon 22.1:
    - Alt+Tab / Alt+Shift+Tab (Alternar Janelas)
    - Alt+F4 (Fechar Janela)
    - Alt+Espaço (Menu da Janela)
    - Alt+F2 (Caixa Executar Comando)
    - Ctrl+Alt+Delete (Menu de Logout / Desligar)
    - Super+D / Ctrl+Alt+D (Mostrar Área de Trabalho)
    - Super+E (Abrir Gerenciador de Arquivos Nemo)
    - Super+L / Ctrl+Alt+L (Bloquear Tela)
    - Ctrl+Alt+Esc (Reiniciar Cinnamon)
    - PrintScreen / Alt+PrintScreen (Captura de Tela)
    - Ctrl+Alt+F1..F6 (Alternar Consoles TTY)
    - Tecla Windows / Super (Menu Principal)
    com suporte completo a Multiseat e persistência pós-reboot.
    """
    script = GSETTINGS_ENV_SETUP + """
        echo "Aplicando bloqueio total de combinações de teclas permanente (Cinnamon/GNOME)..."

        # 1. Sinalizador de persistência
        sudo touch /etc/keybindings_locked

        # 2. Configura trava do dconf no nível de sistema (/etc/dconf/db/local.d/) para todos os usuários e boots futuros
        sudo mkdir -p /etc/dconf/db/local.d/locks 2>/dev/null || true

        cat << 'EOF' | sudo tee /etc/dconf/db/local.d/00-keybindings-lock > /dev/null
[org/cinnamon/desktop/keybindings/wm]
close=['']
switch-applications=['']
switch-applications-backward=['']
switch-group=['']
switch-group-backward=['']
switch-panels=['']
switch-panels-backward=['']
cycle-windows=['']
cycle-windows-backward=['']
panel-main-menu=['']
activate-window-menu=['']
panel-run-dialog=['']
show-desktop=['']
maximize=['']
unmaximize=['']
minimize=['']
push-snap-left=['']
push-snap-right=['']
switch-to-workspace-left=['']
switch-to-workspace-right=['']
switch-to-workspace-up=['']
switch-to-workspace-down=['']

[org/cinnamon/desktop/keybindings]
overlay-key=''
terminal=['']
restart-cinnamon=['']

[org/cinnamon/desktop/keybindings/media-keys]
logout=['']
shutdown=['']
screensaver=['']
screenshot=['']
window-screenshot=['']
area-screenshot=['']
terminal=['']
home=['']

[org/gnome/desktop/wm/keybindings]
close=['']
switch-applications=['']
switch-applications-backward=['']
switch-group=['']
cycle-windows=['']
panel-main-menu=['']
activate-window-menu=['']
panel-run-dialog=['']
show-desktop=['']
minimize=['']
maximize=['']

[org/gnome/mutter]
overlay-key=''

[org/gnome/settings-daemon/plugins/media-keys]
logout=['']
screensaver=['']
screenshot=['']
window-screenshot=['']
area-screenshot=['']
terminal=['']
home=['']
EOF

        cat << 'EOF' | sudo tee /etc/dconf/db/local.d/locks/keybindings > /dev/null
/org/cinnamon/desktop/keybindings/wm/close
/org/cinnamon/desktop/keybindings/wm/switch-applications
/org/cinnamon/desktop/keybindings/wm/switch-applications-backward
/org/cinnamon/desktop/keybindings/wm/switch-group
/org/cinnamon/desktop/keybindings/wm/switch-group-backward
/org/cinnamon/desktop/keybindings/wm/switch-panels
/org/cinnamon/desktop/keybindings/wm/switch-panels-backward
/org/cinnamon/desktop/keybindings/wm/cycle-windows
/org/cinnamon/desktop/keybindings/wm/cycle-windows-backward
/org/cinnamon/desktop/keybindings/wm/panel-main-menu
/org/cinnamon/desktop/keybindings/wm/activate-window-menu
/org/cinnamon/desktop/keybindings/wm/panel-run-dialog
/org/cinnamon/desktop/keybindings/wm/show-desktop
/org/cinnamon/desktop/keybindings/wm/switch-to-workspace-left
/org/cinnamon/desktop/keybindings/wm/switch-to-workspace-right
/org/cinnamon/desktop/keybindings/overlay-key
/org/cinnamon/desktop/keybindings/terminal
/org/cinnamon/desktop/keybindings/restart-cinnamon
/org/cinnamon/desktop/keybindings/media-keys/logout
/org/cinnamon/desktop/keybindings/media-keys/shutdown
/org/cinnamon/desktop/keybindings/media-keys/screensaver
/org/cinnamon/desktop/keybindings/media-keys/screenshot
/org/cinnamon/desktop/keybindings/media-keys/window-screenshot
/org/cinnamon/desktop/keybindings/media-keys/area-screenshot
/org/cinnamon/desktop/keybindings/media-keys/home
/org/gnome/desktop/wm/keybindings/close
/org/gnome/desktop/wm/keybindings/switch-applications
/org/gnome/desktop/wm/keybindings/panel-main-menu
/org/gnome/desktop/wm/keybindings/activate-window-menu
/org/gnome/desktop/wm/keybindings/panel-run-dialog
/org/gnome/desktop/wm/keybindings/show-desktop
/org/gnome/mutter/overlay-key
/org/gnome/settings-daemon/plugins/media-keys/logout
/org/gnome/settings-daemon/plugins/media-keys/screensaver
/org/gnome/settings-daemon/plugins/media-keys/screenshot
EOF

        sudo dconf update 2>/dev/null || true

        # 3. Desativa alternância para Consoles Virtuais (TTY Ctrl+Alt+F1..F6) no servidor X11
        if command -v setxkbmap >/dev/null 2>&1; then
            setxkbmap -option srvrkeys:none 2>/dev/null || true
        fi

        # 4. Script autostart XDG para aplicar a cada login de usuário (inclusive multiseat e xmodmap)
        sudo mkdir -p /etc/xdg/autostart 2>/dev/null || true
        
        cat << 'EOF' | sudo tee /usr/local/bin/apply_keybindings_lock.sh > /dev/null
#!/bin/bash
if [ -f "/etc/keybindings_locked" ]; then
    USER_ID=$(id -u)
    if [ -S "/run/user/$USER_ID/bus" ]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus"
    fi
    export DISPLAY="${DISPLAY:-:0}"

    gsettings set org.cinnamon.desktop.keybindings.wm close "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.wm switch-applications "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.wm switch-applications-backward "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.wm activate-window-menu "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.wm panel-run-dialog "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.wm show-desktop "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.wm panel-main-menu "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings overlay-key '' 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.terminal "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings restart-cinnamon "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.media-keys logout "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.media-keys screensaver "['']" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.keybindings.media-keys screenshot "['']" 2>/dev/null || true

    if command -v setxkbmap >/dev/null 2>&1; then
        setxkbmap -option srvrkeys:none 2>/dev/null || true
    fi

    if command -v xmodmap >/dev/null 2>&1; then
        xmodmap -e "keysym Super_L = NoSymbol" 2>/dev/null || true
        xmodmap -e "keysym Super_R = NoSymbol" 2>/dev/null || true
    fi
fi
EOF
        sudo chmod +x /usr/local/bin/apply_keybindings_lock.sh 2>/dev/null || true

        cat << 'EOF' | sudo tee /etc/xdg/autostart/lock_keybindings.desktop > /dev/null
[Desktop Entry]
Type=Application
Name=Lock Keybindings Autostart
Exec=/usr/local/bin/apply_keybindings_lock.sh
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF

        # 5. Aplicação imediata no contexto da sessão do usuário atual
        gsettings set org.cinnamon.desktop.keybindings.wm close "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm switch-applications "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm switch-applications-backward "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm switch-group "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm cycle-windows "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm activate-window-menu "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm panel-run-dialog "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm show-desktop "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm panel-main-menu "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings overlay-key '' 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.terminal "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings restart-cinnamon "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.media-keys logout "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.media-keys screensaver "['']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.media-keys screenshot "['']" 2>/dev/null || true

        dconf write /org/cinnamon/desktop/keybindings/wm/close "['']" 2>/dev/null || true
        dconf write /org/cinnamon/desktop/keybindings/wm/switch-applications "['']" 2>/dev/null || true
        dconf write /org/cinnamon/desktop/keybindings/wm/activate-window-menu "['']" 2>/dev/null || true
        dconf write /org/cinnamon/desktop/keybindings/wm/panel-run-dialog "['']" 2>/dev/null || true
        dconf write /org/cinnamon/desktop/keybindings/wm/show-desktop "['']" 2>/dev/null || true
        dconf write /org/cinnamon/desktop/keybindings/wm/panel-main-menu "['']" 2>/dev/null || true
        dconf write /org/cinnamon/desktop/keybindings/overlay-key "''" 2>/dev/null || true
        dconf write /org/cinnamon/desktop/keybindings/terminal "['']" 2>/dev/null || true
        dconf write /org/cinnamon/desktop/keybindings/media-keys/logout "['']" 2>/dev/null || true

        if command -v xmodmap >/dev/null 2>&1; then
            xmodmap -e "keysym Super_L = NoSymbol" 2>/dev/null || true
            xmodmap -e "keysym Super_R = NoSymbol" 2>/dev/null || true
        fi

        touch "$HOME/.keybindings_locked" 2>/dev/null || true
        echo "Todas as combinações de teclas (Alt+Tab, Alt+F4, Alt+Espaço, Alt+F2, Ctrl+Alt+Del, Super+D, Super+E, Super+L, PrintScreen, TTY) bloqueadas com sucesso."
    """
    return script.strip(), None

@register_command('desbloquear_combinacoes_teclas', 'Desbloquear Combinações de Teclas', 'Controle da Interface', icon='unlock')
def _build_unlock_keybindings_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Restaura todas as combinações de teclas padrão do sistema no Linux Mint Cinnamon 22.1 e remove a persistência.
    """
    script = GSETTINGS_ENV_SETUP + """
        echo "Removendo bloqueio permanente e restaurando todas as combinações de teclas..."

        # 1. Remove arquivos de persistência do sistema
        sudo rm -f /etc/keybindings_locked 2>/dev/null || true
        sudo rm -f /etc/dconf/db/local.d/00-keybindings-lock 2>/dev/null || true
        sudo rm -f /etc/dconf/db/local.d/locks/keybindings 2>/dev/null || true
        sudo rm -f /etc/xdg/autostart/lock_keybindings.desktop 2>/dev/null || true
        sudo rm -f /usr/local/bin/apply_keybindings_lock.sh 2>/dev/null || true

        sudo dconf update 2>/dev/null || true

        # 2. Reseta valores no gsettings e dconf do usuário
        gsettings reset org.cinnamon.desktop.keybindings.wm close 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm switch-applications 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm switch-applications-backward 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm switch-group 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm switch-group-backward 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm switch-panels 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm switch-panels-backward 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm cycle-windows 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm cycle-windows-backward 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm panel-main-menu 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm activate-window-menu 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm panel-run-dialog 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm show-desktop 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm switch-to-workspace-left 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.wm switch-to-workspace-right 2>/dev/null || true

        gsettings reset org.cinnamon.desktop.keybindings overlay-key 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings terminal 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.terminal 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings restart-cinnamon 2>/dev/null || true

        gsettings reset org.cinnamon.desktop.keybindings.media-keys logout 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.media-keys shutdown 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.media-keys screensaver 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.media-keys screenshot 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.media-keys window-screenshot 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.media-keys area-screenshot 2>/dev/null || true
        gsettings reset org.cinnamon.desktop.keybindings.media-keys home 2>/dev/null || true

        gsettings reset org.gnome.desktop.wm.keybindings close 2>/dev/null || true
        gsettings reset org.gnome.desktop.wm.keybindings switch-applications 2>/dev/null || true
        gsettings reset org.gnome.desktop.wm.keybindings switch-applications-backward 2>/dev/null || true
        gsettings reset org.gnome.desktop.wm.keybindings switch-group 2>/dev/null || true
        gsettings reset org.gnome.desktop.wm.keybindings cycle-windows 2>/dev/null || true
        gsettings reset org.gnome.desktop.wm.keybindings panel-main-menu 2>/dev/null || true
        gsettings reset org.gnome.desktop.wm.keybindings activate-window-menu 2>/dev/null || true
        gsettings reset org.gnome.desktop.wm.keybindings panel-run-dialog 2>/dev/null || true
        gsettings reset org.gnome.desktop.wm.keybindings show-desktop 2>/dev/null || true
        gsettings reset org.gnome.mutter overlay-key 2>/dev/null || true

        dconf reset /org/cinnamon/desktop/keybindings/wm/close 2>/dev/null || true
        dconf reset /org/cinnamon/desktop/keybindings/wm/switch-applications 2>/dev/null || true
        dconf reset /org/cinnamon/desktop/keybindings/wm/panel-main-menu 2>/dev/null || true
        dconf reset /org/cinnamon/desktop/keybindings/overlay-key 2>/dev/null || true
        dconf reset /org/cinnamon/desktop/keybindings/terminal 2>/dev/null || true
        dconf reset /org/cinnamon/desktop/keybindings/restart-cinnamon 2>/dev/null || true
        dconf reset /org/cinnamon/desktop/keybindings/media-keys/logout 2>/dev/null || true

        # 3. Restaura opcoes do teclado X11
        if command -v setxkbmap >/dev/null 2>&1; then
            setxkbmap -option "" 2>/dev/null || true
            setxkbmap 2>/dev/null || true
        fi

        rm -f "$HOME/.keybindings_locked" 2>/dev/null || true
        echo "Combinações de teclas restauradas com sucesso."
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

@register_command('logar_aluno', 'Logar Usuário (Reiniciar Tela de Login)', 'Ações Remotas', icon='user-check')
def _build_login_aluno_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Reinicia o gerenciador de display (lightdm ou gdm3) para forçar o login ou autologin."""
    script = """
        echo "Reiniciando o gerenciador de display..."
        if systemctl is-active --quiet lightdm; then
            sudo systemctl restart lightdm
            echo "LightDM reiniciado com sucesso."
        elif systemctl is-active --quiet gdm3; then
            sudo systemctl restart gdm3
            echo "GDM3 reiniciado com sucesso."
        else
            echo "Gerenciador de display ativo não encontrado (testado: lightdm, gdm3). Tentando iniciar lightdm..."
            sudo systemctl start lightdm || echo "Falha ao iniciar lightdm."
        fi
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
        TERM_BINS=(
            "/usr/bin/gnome-terminal"
            "/usr/bin/gnome-terminal.real"
            "/usr/libexec/gnome-terminal-server"
            "/usr/lib/gnome-terminal/gnome-terminal-server"
            "/usr/bin/mate-terminal"
            "/usr/bin/xfce4-terminal"
            "/usr/bin/xterm"
            "/usr/bin/uxterm"
            "/usr/bin/lxterminal"
            "/usr/bin/tilix"
            "/usr/bin/terminator"
            "/usr/bin/konsole"
            "/usr/bin/alacritty"
            "/usr/bin/kitty"
            "/usr/bin/qterminal"
            "/usr/bin/x-terminal-emulator"
        )
        for bin_path in "${TERM_BINS[@]}"; do
            if [ -e "$bin_path" ]; then
                sudo chmod 755 "$bin_path" 2>/dev/null || true
            fi
        done
        gsettings set org.cinnamon.desktop.lockdown disable-command-line false 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.terminal "['<Primary><Alt>t']" 2>/dev/null || true
        gsettings set org.gnome.desktop.lockdown disable-command-line false 2>/dev/null || true
        gsettings set org.mate.lockdown disable-command-line false 2>/dev/null || true
        DCONF_BIN=$(which dconf-editor)
        if [ -n "$DCONF_BIN" ]; then
            sudo setfacl -x u:aluno "$DCONF_BIN" 2>/dev/null || true
            sudo chmod 755 "$DCONF_BIN" 2>/dev/null || true
        fi

        # 4. Interface (Ícones e Barra de Tarefas)
        echo "[4/5] Restaurando visual da interface e barra de tarefas..."
        SEEN_USERS=""
        for U_DIR in /run/user/[1-9]* /home/*; do
            [ -e "$U_DIR" ] || continue
            U_BASE=$(basename "$U_DIR")
            if [[ "$U_BASE" =~ ^[0-9]+$ ]]; then
                U_UID="$U_BASE"
                U_NAME=$(getent passwd "$U_UID" 2>/dev/null | cut -d: -f1)
            else
                U_NAME="$U_BASE"
                U_UID=$(id -u "$U_NAME" 2>/dev/null)
            fi
            [ -z "$U_NAME" ] || [ "$U_NAME" = "root" ] || [ -z "$U_UID" ] || [ "$U_UID" -lt 1000 ] && continue
            if [[ " $SEEN_USERS " =~ " $U_NAME " ]]; then continue; fi
            SEEN_USERS="$SEEN_USERS $U_NAME"
            
            U_BUS="/run/user/$U_UID/bus"
            U_BUS_ARG=""
            [ -S "$U_BUS" ] && U_BUS_ARG="DBUS_SESSION_BUS_ADDRESS=unix:path=$U_BUS"
            U_DISP=$(ps -u "$U_NAME" -o args 2>/dev/null | grep -oP ':[0-9]+' | head -n 1)
            [ -z "$U_DISP" ] && U_DISP=":0"
            
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.nemo.desktop computer-icon-visible true 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.nemo.desktop home-icon-visible true 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.nemo.desktop trash-icon-visible true 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.nemo.desktop network-icon-visible true 2>/dev/null || true
            sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon.desktop.background show-desktop-icons true 2>/dev/null || true
            
            PANEL_IDS=$(sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings get org.cinnamon panels-enabled 2>/dev/null | grep -o -E "[0-9]+:[0-9]+:[a-zA-Z]+" | cut -d: -f1 | sort -u)
            if [ -n "$PANEL_IDS" ]; then
                for id in $PANEL_IDS; do
                    sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon panels-autohide "['$id:false']" 2>/dev/null || true
                done
            else
                sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon panels-autohide "['1:false', '2:false']" 2>/dev/null || true
            fi
            
            U_HOME=$(getent passwd "$U_NAME" | cut -d: -f6)
            [ -z "$U_HOME" ] && U_HOME="/home/$U_NAME"
            BACKUP_FILE="$U_HOME/.applet_config_backup"
            if [ -f "$BACKUP_FILE" ]; then
                SAVED_APPLETS=$(cat "$BACKUP_FILE")
                if [ -n "$SAVED_APPLETS" ]; then
                    sudo -u "$U_NAME" env $U_BUS_ARG DISPLAY="$U_DISP" gsettings set org.cinnamon enabled-applets "$SAVED_APPLETS" 2>/dev/null || true
                fi
                rm -f "$BACKUP_FILE"
            fi
        done

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

# --- Gerenciamento de Softwares / Pacotes (Nemo, ScratchJR, GCompris, TuxPaint, LibreOffice, Calculadora) ---
@register_command('remover_nemo', 'Remover Nemo e Cinnamon', 'Gerenciamento do Sistema', icon='trash-2', is_streaming=True)
def _build_remove_nemo_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Removendo Nemo e Gerenciador Cinnamon..."
        sudo apt-get purge -y nemo nemo-fileroller cinnamon-desktop-environment cinnamon 2>/dev/null || true
        sudo apt-get autoremove -y 2>/dev/null || true
        echo "Nemo e Cinnamon removidos com sucesso."
    """
    return script.strip(), None

@register_command('instalar_nemo', 'Instalar Nemo e Cinnamon', 'Gerenciamento do Sistema', icon='download', is_streaming=True)
def _build_install_nemo_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Instalando Nemo e Gerenciador Cinnamon..."
        sudo apt-get update -qq && sudo apt-get install -y nemo cinnamon-desktop-environment 2>/dev/null || true
        echo "Nemo e Cinnamon instalados com sucesso."
    """
    return script.strip(), None

@register_command('desinstalar_scratchjr', 'Desinstalar ScratchJR', 'Gerenciamento do Sistema', icon='trash-2', is_streaming=True)
def _build_uninstall_scratchjr_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Desinstalando ScratchJR..."
        flatpak uninstall -y org.scratch.ScratchJr 2>/dev/null || snap remove scratchjr 2>/dev/null || sudo apt-get remove -y scratchjr 2>/dev/null || true
        echo "ScratchJR desinstalado com sucesso."
    """
    return script.strip(), None

@register_command('instalar_scratchjr', 'Instalar ScratchJR', 'Gerenciamento do Sistema', icon='download', is_streaming=True)
def _build_install_scratchjr_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Instalando ScratchJR..."
        flatpak install -y flathub org.scratch.ScratchJr 2>/dev/null || snap install scratchjr 2>/dev/null || true
        echo "ScratchJR instalado com sucesso."
    """
    return script.strip(), None

@register_command('desinstalar_gcompris', 'Desinstalar GCompris (Flatpak)', 'Gerenciamento do Sistema', icon='trash-2', is_streaming=True)
def _build_uninstall_gcompris_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Desinstalando GCompris..."
        flatpak uninstall -y net.gcompris.GCompris 2>/dev/null || sudo apt-get remove -y gcompris-qt 2>/dev/null || true
        echo "GCompris desinstalado com sucesso."
    """
    return script.strip(), None

@register_command('instalar_gcompris', 'Instalar GCompris (Flatpak)', 'Gerenciamento do Sistema', icon='download', is_streaming=True)
def _build_install_gcompris_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Instalando GCompris..."
        flatpak install -y flathub net.gcompris.GCompris 2>/dev/null || (sudo apt-get update -qq && sudo apt-get install -y gcompris-qt) 2>/dev/null || true
        echo "GCompris instalado com sucesso."
    """
    return script.strip(), None

@register_command('desinstalar_tuxpaint', 'Desinstalar Tux Paint (Flatpak)', 'Gerenciamento do Sistema', icon='trash-2', is_streaming=True)
def _build_uninstall_tuxpaint_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Desinstalando Tux Paint..."
        flatpak uninstall -y org.tuxpaint.Tuxpaint 2>/dev/null || sudo apt-get remove -y tuxpaint 2>/dev/null || true
        echo "Tux Paint desinstalado com sucesso."
    """
    return script.strip(), None

@register_command('instalar_tuxpaint', 'Instalar Tux Paint (Flatpak)', 'Gerenciamento do Sistema', icon='download', is_streaming=True)
def _build_install_tuxpaint_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Instalando Tux Paint..."
        flatpak install -y flathub org.tuxpaint.Tuxpaint 2>/dev/null || (sudo apt-get update -qq && sudo apt-get install -y tuxpaint) 2>/dev/null || true
        echo "Tux Paint instalado com sucesso."
    """
    return script.strip(), None

@register_command('desinstalar_libreoffice', 'Desinstalar LibreOffice', 'Gerenciamento do Sistema', icon='trash-2', is_streaming=True)
def _build_uninstall_libreoffice_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Desinstalando LibreOffice..."
        sudo apt-get purge -y "libreoffice*" 2>/dev/null || flatpak uninstall -y org.libreoffice.LibreOffice 2>/dev/null || true
        sudo apt-get autoremove -y 2>/dev/null || true
        echo "LibreOffice desinstalado com sucesso."
    """
    return script.strip(), None

@register_command('instalar_libreoffice', 'Instalar LibreOffice', 'Gerenciamento do Sistema', icon='download', is_streaming=True)
def _build_install_libreoffice_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Instalando LibreOffice..."
        sudo apt-get update -qq && sudo apt-get install -y libreoffice libreoffice-l10n-pt-br 2>/dev/null || true
        echo "LibreOffice instalado com sucesso."
    """
    return script.strip(), None

@register_command('desinstalar_calculadora', 'Desinstalar Calculadora', 'Gerenciamento do Sistema', icon='trash-2', is_streaming=True)
def _build_uninstall_calculator_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Desinstalando Calculadora..."
        sudo apt-get remove -y gnome-calculator 2>/dev/null || snap remove gnome-calculator 2>/dev/null || true
        echo "Calculadora desinstalada com sucesso."
    """
    return script.strip(), None

@register_command('instalar_calculadora', 'Instalar Calculadora', 'Gerenciamento do Sistema', icon='download', is_streaming=True)
def _build_install_calculator_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Instalando Calculadora..."
        sudo apt-get update -qq && sudo apt-get install -y gnome-calculator 2>/dev/null || true
        echo "Calculadora instalada com sucesso."
    """
    return script.strip(), None

@register_command('monitorar_rede', 'Monitorar Tráfego de Rede', 'Monitoramento', icon='activity', is_streaming=True)
def _build_monitor_network_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "--- Estatísticas de Tráfego de Rede ---"
        ip -s link 2>/dev/null || ifconfig 2>/dev/null
    """
    return script.strip(), None

@register_command('testar_velocidade', 'Testar Velocidade da Internet', 'Monitoramento', icon='zap', is_streaming=True)
def _build_test_speed_command(data: Dict[str, Any]) -> Tuple[str, None]:
    script = """
        echo "Iniciando teste de velocidade de rede..."
        speedtest-cli --simple 2>/dev/null || speedtest 2>/dev/null || curl -s https://raw.githubusercontent.com/sivel/speedtest-cli/master/speedtest.py | python3 - --simple 2>/dev/null || echo "speedtest-cli não instalado no cliente."
    """
    return script.strip(), None

def _get_command_builder(action: str):
    """Retorna o construtor de comando para a ação especificada."""
    import sys
    cb_mod = sys.modules.get('command_builder') or sys.modules.get(__name__)
    if cb_mod and hasattr(cb_mod, 'COMMANDS'):
        return cb_mod.COMMANDS.get(action)
    return COMMANDS.get(action)

@register_command('ativar_dns_familia', 'Ativar DNS Familiar', 'Configurações de Rede', icon='shield')
def _build_enable_family_dns(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Configura o Cloudflare Family DNS (1.1.1.3) para bloquear malware e conteúdo adulto.
    Usa nmcli e fallback em resolv.conf para máxima compatibilidade.
    """
    script = """
        # Busca a conexão ativa principal de forma universal (compatível com todas as versões do NetworkManager)
        CONN_UUID=$(nmcli -t -f UUID,TYPE connection show --active | grep -iE "ethernet|wireless|wifi|802-3|802-11|lan" | head -n1 | cut -d: -f1)
        
        if [ -z "$CONN_UUID" ]; then
            CONN_UUID=$(nmcli -t -f UUID connection show --active | grep -v "00000000" | head -n1)
        fi

        if [ -n "$CONN_UUID" ]; then
            echo "Configurando DNS Familiar na conexão ($CONN_UUID)..."
            sudo nmcli connection modify "$CONN_UUID" ipv4.dns "1.1.1.3 1.0.0.3"
            sudo nmcli connection modify "$CONN_UUID" ipv4.ignore-auto-dns yes
            sudo nmcli connection up "$CONN_UUID"
            echo "DNS Familiar (Cloudflare) ativado com sucesso."
        else
            echo "Aplicando fallback de DNS Familiar..."
            if [ -f /etc/systemd/resolved.conf ]; then
                sudo sed -i 's/#\\?DNS=.*/DNS=1.1.1.3 1.0.0.3/' /etc/systemd/resolved.conf
                sudo systemctl restart systemd-resolved 2>/dev/null || true
            fi
            echo "nameserver 1.1.1.3" | sudo tee /etc/resolv.conf > /dev/null
            echo "nameserver 1.0.0.3" | sudo tee -a /etc/resolv.conf > /dev/null
            echo "DNS Familiar (Cloudflare 1.1.1.3) ativado com sucesso."
        fi
    """
    return script.strip(), None

@register_command('desativar_dns_familia', 'Desativar DNS Familiar', 'Configurações de Rede', icon='shield-off')
def _build_disable_family_dns(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Remove a configuração de DNS fixo e volta a aceitar o DNS automático da rede (DHCP).
    """
    script = """
        CONN_UUID=$(nmcli -t -f UUID,TYPE connection show --active | grep -iE "ethernet|wireless|wifi|802-3|802-11|lan" | head -n1 | cut -d: -f1)
        
        if [ -z "$CONN_UUID" ]; then
            CONN_UUID=$(nmcli -t -f UUID connection show --active | grep -v "00000000" | head -n1)
        fi

        if [ -n "$CONN_UUID" ]; then
            echo "Restaurando DNS automático na conexão ($CONN_UUID)..."
            sudo nmcli connection modify "$CONN_UUID" ipv4.dns ""
            sudo nmcli connection modify "$CONN_UUID" ipv4.ignore-auto-dns no
            sudo nmcli connection up "$CONN_UUID"
            echo "DNS Familiar desativado. A máquina agora utiliza as configurações padrão da rede."
        else
            if [ -f /etc/systemd/resolved.conf ]; then
                sudo sed -i 's/#\\?DNS=.*/#DNS=/' /etc/systemd/resolved.conf
                sudo systemctl restart systemd-resolved 2>/dev/null || true
            fi
            echo "DNS Familiar desativado."
        fi
    """
    return script.strip(), None

@register_command('ativar_safesearch', 'Ativar SafeSearch & YouTube Restrito', 'Configurações de Rede', icon='shield-check')
def _build_enable_safesearch(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Força busca segura no Google (forcesafesearch.google.com), Bing (strict.bing.com),
    DuckDuckGo e Modo Restrito Estrito no YouTube (restrict.youtube.com).
    Aplica redirecionamentos VIP no /etc/hosts e no dnsmasq se instalado.
    """
    script = """
        echo "Configurando SafeSearch (Google, Bing, DuckDuckGo) e Modo Restrito (YouTube)..."

        # 1. Atualizar /etc/hosts removendo bloco antigo se existir
        sudo sed -i '/# BEGIN SAFESEARCH/,/# END SAFESEARCH/d' /etc/hosts

        cat << 'EOF' | sudo tee -a /etc/hosts > /dev/null

# BEGIN SAFESEARCH
# VIP IPs Oficiais para SafeSearch Estrito
216.239.38.120 www.google.com google.com www.google.com.br google.com.br
216.239.38.120 www.youtube.com youtube.com m.youtube.com youtube-nocookie.com www.youtube-nocookie.com
204.79.197.220 www.bing.com bing.com
52.142.124.215 duckduckgo.com www.duckduckgo.com safe.duckduckgo.com
# END SAFESEARCH
EOF

        # 2. Configurar dnsmasq se estiver instalado
        if [ -d /etc/dnsmasq.d ]; then
            cat << 'EOF' | sudo tee /etc/dnsmasq.d/safesearch.conf > /dev/null
# Configuração de SafeSearch e YouTube Restrito
address=/google.com/216.239.38.120
address=/www.google.com/216.239.38.120
address=/google.com.br/216.239.38.120
address=/www.google.com.br/216.239.38.120
address=/youtube.com/216.239.38.120
address=/www.youtube.com/216.239.38.120
address=/m.youtube.com/216.239.38.120
address=/youtube-nocookie.com/216.239.38.120
address=/www.youtube-nocookie.com/216.239.38.120
address=/bing.com/204.79.197.220
address=/www.bing.com/204.79.197.220
address=/duckduckgo.com/52.142.124.215
address=/www.duckduckgo.com/52.142.124.215
EOF
            if systemctl is-active --quiet dnsmasq; then
                sudo systemctl restart dnsmasq || true
            fi
        fi

        # 3. Limpar cache de DNS local se systemd-resolved estiver rodando
        if systemctl is-active --quiet systemd-resolved; then
            sudo systemd-resolve --flush-caches 2>/dev/null || sudo resolvectl flush-caches 2>/dev/null || true
        fi

        echo "✅ SafeSearch (Google/Bing/DuckDuckGo) e YouTube Restrito ATIVADOS com sucesso!"
    """
    return script.strip(), None

@register_command('desativar_safesearch', 'Desativar SafeSearch & YouTube Restrito', 'Configurações de Rede', icon='shield-off')
def _build_disable_safesearch(data: Dict[str, Any]) -> Tuple[str, None]:
    """Remove o redirecionamento de SafeSearch e YouTube Restrito."""
    script = """
        echo "Desativando SafeSearch e Modo Restrito no YouTube..."

        sudo sed -i '/# BEGIN SAFESEARCH/,/# END SAFESEARCH/d' /etc/hosts

        if [ -f /etc/dnsmasq.d/safesearch.conf ]; then
            sudo rm -f /etc/dnsmasq.d/safesearch.conf
            if systemctl is-active --quiet dnsmasq; then
                sudo systemctl restart dnsmasq || true
            fi
        fi

        if systemctl is-active --quiet systemd-resolved; then
            sudo systemd-resolve --flush-caches 2>/dev/null || sudo resolvectl flush-caches 2>/dev/null || true
        fi

        echo "✅ SafeSearch e Modo Restrito no YouTube DESATIVADOS."
    """
    return script.strip(), None

@register_command('verificar_safesearch', 'Testar Status do SafeSearch', 'Configurações de Rede', icon='check-circle')
def _build_verify_safesearch(data: Dict[str, Any]) -> Tuple[str, None]:
    """Testa se as requisições para Google, YouTube e Bing estão sendo redirecionadas para os VIPs de SafeSearch."""
    script = """
        echo "--- STATUS DO SAFESEARCH E YOUTUBE RESTRITO ---"

        G_IP=$(getent hosts www.google.com | awk '{print $1}' | head -n1)
        Y_IP=$(getent hosts www.youtube.com | awk '{print $1}' | head -n1)
        B_IP=$(getent hosts www.bing.com | awk '{print $1}' | head -n1)

        echo -n "Google (www.google.com): "
        if [ "$G_IP" = "216.239.38.120" ]; then
            echo "✅ FORÇADO (forcesafesearch.google.com -> $G_IP)"
        else
            echo "❌ DESATIVADO (IP detectado: ${G_IP:-Nenhum})"
        fi

        echo -n "YouTube (www.youtube.com): "
        if [ "$Y_IP" = "216.239.38.120" ]; then
            echo "✅ MODO RESTRITO FORÇADO (restrict.youtube.com -> $Y_IP)"
        else
            echo "❌ DESATIVADO (IP detectado: ${Y_IP:-Nenhum})"
        fi

        echo -n "Bing (www.bing.com): "
        if [ "$B_IP" = "204.79.197.220" ]; then
            echo "✅ SAFESEARCH ESTRITO FORÇADO (strict.bing.com -> $B_IP)"
        else
            echo "❌ DESATIVADO (IP detectado: ${B_IP:-Nenhum})"
        fi
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

    # Validação de formato de domínio
    domain_regex = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,6}$")
    for site in site_list:
        if not domain_regex.match(site):
            return None, {"success": False, "message": f"O domínio '{site}' está mal formatado. Por favor, insira domínios válidos (ex: exemplo.com)."}


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

    # Criamos o arquivo usando um Heredoc no shell para lidar com múltiplas linhas de forma limpa.
    # Usamos 'EOF_WHITELIST' entre aspas simples para evitar expansão de variáveis indesejadas pelo shell.
    script = f"""
        set -e
        CONN_UUID=$(nmcli -t -f UUID,TYPE,STATE connection show --active | grep -E ":802-3-ethernet|:802-11-wireless" | head -n1 | cut -d: -f1)
        if [ -z "$CONN_UUID" ]; then echo "Erro: Conexão ativa (Ethernet/Wi-Fi) não encontrada." >&2; exit 1; fi

        if ! command -v dnsmasq &> /dev/null; then
            sudo apt-get update -qq && sudo apt-get install -y dnsmasq || {{ echo "Erro: Falha ao instalar dnsmasq. Verifique a conexão com a internet." >&2; exit 1; }}
        fi

        sudo mkdir -p /etc/dnsmasq.d
        [ -d /etc/dnsmasq.d.bak/ ] || sudo mkdir -p /etc/dnsmasq.d.bak/

        sudo bash -c 'shopt -s nullglob; files=(/etc/dnsmasq.d/*); [ ${{#files[@]}} -gt 0 ] && mv "${{files[@]}}" /etc/dnsmasq.d.bak/' || true

        echo "Criando arquivo de configuração de whitelist para dnsmasq..."
        TEMP_FILE=$(mktemp)
        cat <<'EOF_WHITELIST' > "$TEMP_FILE"
{dnsmasq_config_content}
EOF_WHITELIST
        sudo mv "$TEMP_FILE" /etc/dnsmasq.d/whitelist.conf
        sudo chmod 644 /etc/dnsmasq.d/whitelist.conf

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

@register_command('incluir_whitelist', 'Incluir na Whitelist', 'Configurações de Rede', icon='plus-square', require_field='whitelist-sites-group')
def _build_include_whitelist_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Adiciona domínios ao arquivo de whitelist existente sem sobrescrevê-lo."""
    sites_raw = data.get('sites', '')
    site_list = [s.strip() for s in re.split(r'[,\s\n]+', sites_raw) if s.strip()]
    if not site_list:
        return None, {"success": False, "message": "A lista de sites não pode estar vazia."}

    domain_regex = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,6}$")
    lines = []
    for site in site_list:
        if not domain_regex.match(site):
            return None, {"success": False, "message": f"Domínio '{site}' mal formatado."}
        
        for s in [site, f"www.{site}" if not site.startswith('www.') else None]:
            if s:
                safe_s = shlex.quote(s)
                lines.append(f"if ! grep -q '/{safe_s}/' /etc/dnsmasq.d/whitelist.conf; then echo 'server=/{safe_s}/1.1.1.1' | sudo tee -a /etc/dnsmasq.d/whitelist.conf > /dev/null; fi")

    script = f"""
        if [ ! -f /etc/dnsmasq.d/whitelist.conf ]; then
            echo "Erro: Whitelist não está ativa. Use 'Ativar Whitelist' primeiro." >&2
            exit 1
        fi
        {" ".join(lines)}
        sudo systemctl restart dnsmasq
        echo "Sites incluídos com sucesso."
    """
    return script.strip(), None

@register_command('remover_whitelist', 'Excluir da Whitelist', 'Configurações de Rede', icon='minus-square', require_field='whitelist-sites-group')
def _build_remove_whitelist_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Remove domínios específicos do arquivo de whitelist."""
    sites_raw = data.get('sites', '')
    site_list = [s.strip() for s in re.split(r'[,\s\n]+', sites_raw) if s.strip()]
    if not site_list:
        return None, {"success": False, "message": "Informe os sites para remover."}

    lines = []
    for site in site_list:
        # Escapa os pontos para a regex do sed e constrói o padrão
        escaped_site_for_sed = site.replace('.', r'\.')
        lines.append(rf"sudo sed -i '/^server=\/{escaped_site_for_sed}\//d' /etc/dnsmasq.d/whitelist.conf")

    script = f"""
        if [ ! -f /etc/dnsmasq.d/whitelist.conf ]; then
            echo "Erro: Arquivo de whitelist não encontrado." >&2
            exit 1
        fi
        {" ".join(lines)}
        sudo systemctl restart dnsmasq
        echo "Sites removidos com sucesso."
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
        if systemctl list-unit-files | grep -q dnsmasq.service; then
            sudo systemctl stop dnsmasq || true
        fi
        sudo rm -f /etc/dnsmasq.d/whitelist.conf

        # Restaura arquivos de backup se existirem
        LATEST_BAK=$(ls -t /etc/dnsmasq.conf.bak.* 2>/dev/null | head -n 1 || true)
        if [ -n "$LATEST_BAK" ]; then
            sudo mv "$LATEST_BAK" /etc/dnsmasq.conf
        fi
        if [ -d /etc/dnsmasq.d.bak/ ]; then
            sudo bash -c 'shopt -s nullglob; files=(/etc/dnsmasq.d.bak/*); [ ${{#files[@]}} -gt 0 ] && mv "${{files[@]}}" /etc/dnsmasq.d/' || true
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

@register_command('obter_whitelist_raw', 'Ver Conteúdo para Edição', 'Configurações de Rede', icon='edit-3')
def _build_get_whitelist_raw_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Retorna a lista de domínios configurados no dnsmasq para facilitar a edição manual."""
    return """
        CONF_FILE="/etc/dnsmasq.d/whitelist.conf"
        if [ -f "$CONF_FILE" ]; then
            echo "--- COPIE A LISTA ABAIXO ---"
            grep "^server=/" "$CONF_FILE" | cut -d'/' -f2 | grep -v "^www\." | sort -u
        else
            echo "Arquivo de whitelist não encontrado em /etc/dnsmasq.d/"
        fi
    """, None

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

@register_command('listar_sites_bloqueados', 'Listar Sites Bloqueados', 'Configurações de Rede', icon='list')
def _build_list_blocked_sites_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Lista os domínios atualmente bloqueados no arquivo /etc/hosts."""
    script = """
        echo "--- SITES BLOQUEADOS NO /etc/hosts ---"
        grep "^127.0.0.1 " /etc/hosts | grep -v "localhost" | awk '{print $2}' | sort -u
    """
    return script.strip(), None

@register_command('bloquear_redes_sociais_e_ia', 'Bloquear Redes Sociais & Chatbots IA', 'Configurações de Rede', icon='shield')
def _build_block_social_and_ai(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Bloqueia o acesso a Redes Sociais (TikTok, Instagram, Facebook, Twitter, Discord, Reddit)
    e Chatbots de IA (ChatGPT, Character.ai, Claude, Gemini, etc.) via /etc/hosts e dnsmasq.
    """
    social_domains = SITE_CATEGORIES_CONFIG.get('redes_sociais', {}).get('domains', [])
    ai_domains = SITE_CATEGORIES_CONFIG.get('chatbots_ia', {}).get('domains', [])
    
    all_domains = sorted(list(set(social_domains + ai_domains)))
    
    hosts_entries = []
    dnsmasq_entries = []
    
    for domain in all_domains:
        hosts_entries.append(f"127.0.0.1 {domain}")
        dnsmasq_entries.append(f"address=/{domain}/127.0.0.1")
        if not domain.startswith('www.'):
            hosts_entries.append(f"127.0.0.1 www.{domain}")
            dnsmasq_entries.append(f"address=/www.{domain}/127.0.0.1")

    hosts_content = "\n".join(hosts_entries)
    dnsmasq_content = "\n".join(dnsmasq_entries)

    script = f"""
        echo "Aplicando bloqueio de Redes Sociais e Chatbots de IA..."

        # 1. Atualiza /etc/hosts
        sudo sed -i '/# BEGIN BLOCK_SOCIAL_AI/,/# END BLOCK_SOCIAL_AI/d' /etc/hosts

        cat << 'EOF' | sudo tee -a /etc/hosts > /dev/null

# BEGIN BLOCK_SOCIAL_AI
{hosts_content}
# END BLOCK_SOCIAL_AI
EOF

        # 2. Atualiza dnsmasq se instalado
        if [ -d /etc/dnsmasq.d ]; then
            cat << 'EOF' | sudo tee /etc/dnsmasq.d/block_social_ai.conf > /dev/null
# Bloqueio de Redes Sociais e Chatbots de IA
{dnsmasq_content}
EOF
            if systemctl is-active --quiet dnsmasq; then
                sudo systemctl restart dnsmasq || true
            fi
        fi

        if systemctl is-active --quiet systemd-resolved; then
            sudo systemd-resolve --flush-caches 2>/dev/null || sudo resolvectl flush-caches 2>/dev/null || true
        fi

        echo "✅ Bloqueio de Redes Sociais e Chatbots de IA applied com sucesso."
    """
    return script.strip(), None


@register_command('bloquear_stickers', 'Bloquear Stickers e Meu Perfil (Elefante Letrado)', 'Configurações de Rede', icon='slash')
def _build_block_stickers_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Bloqueia o Álbum de Figurinhas/Stickers e o Meu Perfil do Elefante Letrado.
    """
    script = """
        echo "Aplicando bloqueio seguro e exclusivo do Álbum de Figurinhas e Perfil (Elefante Letrado)..."

        # 1. AUTO-REPARO: Restaurar binários originais e remover wrappers agressivos que quebravam outros atalhos (como Matific)
        for B_ELF in /opt/google/chrome/chrome /usr/lib/chromium-browser/chromium-browser /usr/lib/chromium/chromium /opt/brave.com/brave/brave /opt/microsoft/msedge/msedge; do
            B_DIR=$(dirname "$B_ELF")
            B_BASE=$(basename "$B_ELF")
            REAL_ELF="$B_DIR/${B_BASE}.real"
            if [ -f "$REAL_ELF" ]; then
                cp -p "$REAL_ELF" "$B_ELF" 2>/dev/null || true
                rm -f "$REAL_ELF" 2>/dev/null || true
                chmod 755 "$B_ELF" 2>/dev/null || true
            fi
        done

        # Remover wrappers criados em /usr/local/bin
        rm -f /usr/local/bin/google-chrome /usr/local/bin/google-chrome-stable /usr/local/bin/chromium /usr/local/bin/chromium-browser /usr/local/bin/brave-browser /usr/local/bin/microsoft-edge-stable 2>/dev/null || true

        # 2. Criar extensão com escopo ESTRITAMENTE restrito ao Elefante Letrado (Manifest V3)
        mkdir -p /opt/elefante_blocker /etc/elefante_blocker
        chmod 755 /opt/elefante_blocker /etc/elefante_blocker

        cat << 'EOF' > /opt/elefante_blocker/manifest.json
{
  "manifest_version": 3,
  "name": "Elefante Letrado Focus",
  "version": "4.6.0",
  "description": "Foco de Leitura Elefante Letrado",
  "permissions": ["storage"],
  "host_permissions": [
    "*://*.elefanteletrado.com.br/*",
    "*://elefanteletrado.com.br/*"
  ],
  "content_scripts": [
    {
      "matches": [
        "*://*.elefanteletrado.com.br/*",
        "*://elefanteletrado.com.br/*"
      ],
      "js": ["content.js"],
      "run_at": "document_start",
      "all_frames": true
    }
  ]
}
EOF

        cat << 'EOF' > /opt/elefante_blocker/content.js
(function() {
    'use strict';
    
    // Garantir que roda APENAS no domínio do Elefante Letrado
    if (!window.location.hostname.includes('elefanteletrado.com.br')) return;

    var BLOCK_CSS = [
        'a[href*="stickers"]', 'a[href*="sticker"]', 'a[href*="album"]', 'a[href*="figurinhas"]', 'a[href*="figurinha"]', 'a[href*="mundoelefante"]', 'a[href*="profile"]', 'a[href*="perfil"]', 'a[href*="avatar"]', 'a[href*="conquista"]', 'a[href*="trofeu"]', 'a[href*="premio"]', 'a[href*="colecao"]',
        'a[href*="Sticker"]', 'a[href*="Album"]', 'a[href*="Figurinha"]', 'a[href*="Profile"]', 'a[href*="Perfil"]',
        '[ui-sref*="stickers"]', '[ui-sref*="sticker"]', '[ui-sref*="album"]', '[ui-sref*="figurinhas"]', '[ui-sref*="figurinha"]', '[ui-sref*="profile"]', '[ui-sref*="perfil"]', '[ui-sref*="avatar"]', '[ui-sref*="achievement"]',
        '[data-ui-sref*="stickers"]', '[data-ui-sref*="sticker"]', '[data-ui-sref*="album"]', '[data-ui-sref*="figurinhas"]', '[data-ui-sref*="profile"]', '[data-ui-sref*="perfil"]', '[data-ui-sref*="avatar"]',
        '[ng-click*="sticker"]', '[ng-click*="album"]', '[ng-click*="figurinha"]', '[ng-click*="profile"]', '[ng-click*="perfil"]', '[ng-click*="avatar"]', '[ng-click*="conquista"]', '[ng-click*="trofeu"]',
        '[ng-click*="Sticker"]', '[ng-click*="Album"]', '[ng-click*="Figurinha"]', '[ng-click*="Profile"]', '[ng-click*="Perfil"]',
        '[routerlink*="sticker"]', '[routerlink*="album"]', '[routerlink*="figurinha"]', '[routerlink*="profile"]', '[routerlink*="perfil"]', '[routerlink*="avatar"]',
        '[data-route*="sticker"]', '[data-route*="album"]', '[data-route*="figurinha"]', '[data-route*="profile"]', '[data-route*="perfil"]',
        '[data-testid*="sticker"]', '[data-testid*="album"]', '[data-testid*="figurinha"]', '[data-testid*="profile"]', '[data-testid*="perfil"]', '[data-testid*="avatar"]',
        '.menu-stickers', '.menu-album', '.menu-perfil', '.nav-stickers', '.nav-album', '.profile-menu', '.user-profile-btn', '.profile-box', '.avatar-box', '.avatar-img', '.sticker-card', '.album-container',
        '[class*="sticker"]', '[class*="album"]', '[class*="figurinha"]', '[id*="sticker"]', '[id*="album"]', '[id*="figurinha"]',
        '[class*="profile"]', '[id*="profile"]', '[class*="perfil"]', '[id*="perfil"]', '[class*="avatar"]', '[id*="avatar"]',
        'img[src*="sticker"]', 'img[src*="album"]', 'img[src*="figurinha"]', 'img[src*="avatar"]',
        'img[alt*="sticker"]', 'img[alt*="álbum"]', 'img[alt*="album"]', 'img[alt*="figurinha"]', 'img[alt*="perfil"]', 'img[alt*="avatar"]',
        '[class*="modal"][class*="sticker"]', '[class*="modal"][class*="album"]', '[class*="dialog"][class*="sticker"]', '[class*="dialog"][class*="album"]'
    ].join(', ') + ' { display: none !important; pointer-events: none !important; visibility: hidden !important; opacity: 0 !important; max-height: 0 !important; max-width: 0 !important; overflow: hidden !important; }';

    function injectCSS() {
        var el = document.getElementById('el-block-style-fast');
        if (!el) {
            var st = document.createElement('style');
            st.id = 'el-block-style-fast';
            st.textContent = BLOCK_CSS;
            var target = document.head || document.documentElement || document.body;
            if (target) target.appendChild(st);
        }
    }

    // Interceptação de APIs de figurinhas e perfil
    try {
        var origFetch = window.fetch;
        if (origFetch) {
            window.fetch = function(input, init) {
                var url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
                url = (url || '').toLowerCase();
                if (url.includes('sticker') || url.includes('album') || url.includes('figurinha') || url.includes('/profile') || url.includes('/perfil')) {
                    return Promise.reject(new Error('Bloqueado por política pedagógica'));
                }
                return origFetch.apply(this, arguments);
            };
        }
        var origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            var u = (url || '').toString().toLowerCase();
            if (u.includes('sticker') || u.includes('album') || u.includes('figurinha') || u.includes('/profile') || u.includes('/perfil')) {
                this.abort();
                return;
            }
            return origOpen.apply(this, arguments);
        };
    } catch(err) {}

    // Interceptação de clique na fase de captura
    document.addEventListener('click', function(e) {
        try {
            var t = e.target && e.target.closest ? e.target.closest('a, button, [role="button"], [ui-sref], [ng-click], [routerlink], [data-route], li, div, span') : null;
            if (!t) return;
            var href = (t.getAttribute('href') || '').toLowerCase();
            var sref = (t.getAttribute('ui-sref') || t.getAttribute('data-ui-sref') || '').toLowerCase();
            var ngc = (t.getAttribute('ng-click') || '').toLowerCase();
            var rlink = (t.getAttribute('routerlink') || t.getAttribute('data-route') || '').toLowerCase();
            var title = (t.getAttribute('title') || t.getAttribute('aria-label') || '').toLowerCase();
            var txt = (t.textContent || t.innerText || '').trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
            var full = href + ' ' + sref + ' ' + ngc + ' ' + rlink + ' ' + title + ' ' + txt;
            
            var isTarget = full.indexOf('sticker') !== -1 || full.indexOf('album') !== -1 || full.indexOf('figurinha') !== -1 ||
                           full.indexOf('perfil') !== -1 || full.indexOf('profile') !== -1 || full.indexOf('avatar') !== -1 ||
                           full.indexOf('mundoelefante') !== -1 || full.indexOf('mascote') !== -1 || full.indexOf('conquista') !== -1 || full.indexOf('trofeu') !== -1;
                           
            if (isTarget) {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                if (window.location.hash.indexOf('book') === -1) {
                    window.location.hash = '#/books';
                }
                return false;
            }
        } catch(err) {}
    }, true);

    function scanDOM() {
        injectCSS();
        try {
            var targets = document.querySelectorAll('a, button, li, [role="button"], [role="tab"], .menu-item, .nav-item, div.item, div.card, span');
            for (var i = 0; i < targets.length; i++) {
                var el = targets[i];
                if (el.getAttribute('data-el-hidden') === '1') continue;

                var rawTxt = (el.textContent || el.innerText || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('aria-label') || el.getAttribute('src') || '').trim().toLowerCase();
                if (rawTxt.length > 0 && rawTxt.length < 100) {
                    var normTxt = rawTxt.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
                    var isProfileOrSticker = normTxt.indexOf('perfil') !== -1 || normTxt.indexOf('profile') !== -1 ||
                                           normTxt.indexOf('sticker') !== -1 || normTxt.indexOf('figurinha') !== -1 ||
                                           normTxt.indexOf('album') !== -1 || normTxt.indexOf('avatar') !== -1 ||
                                           normTxt.indexOf('mascote') !== -1 || normTxt.indexOf('conquista') !== -1 ||
                                           normTxt.indexOf('trofeu') !== -1 || normTxt.indexOf('premio') !== -1;
                    if (isProfileOrSticker) {
                        var parent = el.closest('li, a, button, [role="button"], .menu-item, .nav-item') || el;
                        parent.setAttribute('data-el-hidden', '1');
                        parent.style.setProperty('display', 'none', 'important');
                        parent.style.setProperty('visibility', 'hidden', 'important');
                        parent.style.setProperty('opacity', '0', 'important');
                        parent.style.setProperty('max-height', '0', 'important');
                        parent.style.setProperty('max-width', '0', 'important');
                        parent.style.setProperty('pointer-events', 'none', 'important');
                    }
                }
            }
        } catch(e) {}
    }

    function checkRoute() {
        var hash = (window.location.hash || '').toLowerCase();
        var path = (window.location.pathname || '').toLowerCase();
        var full = (hash + ' ' + path).normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        if (full.indexOf('sticker') !== -1 || full.indexOf('album') !== -1 || full.indexOf('figurinha') !== -1 ||
            full.indexOf('profile') !== -1 || full.indexOf('perfil') !== -1 || full.indexOf('avatar') !== -1) {
            if (window.location.hash !== '#/books' && window.location.hash !== '#/student/books') {
                window.location.hash = '#/books';
            }
        }
        scanDOM();
    }

    injectCSS();
    checkRoute();

    try {
        var origPush = history.pushState;
        history.pushState = function() {
            origPush.apply(this, arguments);
            checkRoute();
        };
        var origReplace = history.replaceState;
        history.replaceState = function() {
            origReplace.apply(this, arguments);
            checkRoute();
        };
    } catch(e) {}

    window.addEventListener('hashchange', checkRoute, true);
    window.addEventListener('popstate', checkRoute, true);
    window.addEventListener('DOMContentLoaded', scanDOM, true);
    window.addEventListener('load', scanDOM, true);

    var obs = new MutationObserver(scanDOM);
    if (document.documentElement) {
        obs.observe(document.documentElement, { childList: true, subtree: true });
    }

    setInterval(scanDOM, 300);
})();
EOF

        chmod -R 755 /opt/elefante_blocker
        chmod -R 644 /opt/elefante_blocker/*
        chmod 755 /opt/elefante_blocker
        cp -rf /opt/elefante_blocker/* /etc/elefante_blocker/ 2>/dev/null || true

        # 3. Injetar a extensão nos atalhos do Elefante Letrado (Desktop e Menu de Aplicativos)
        find /usr/share/applications /usr/local/share/applications /home /etc/skel -name "*.desktop" 2>/dev/null | while read -r DFILE; do
            if grep -qi "elefante" "$DFILE"; then
                sed -i 's| --load-extension=[^ "]*||g' "$DFILE" 2>/dev/null || true
                sed -i 's|^Exec=\(.*chrome[^ ]*\) |Exec=\1 --load-extension=/opt/elefante_blocker |g' "$DFILE" 2>/dev/null || true
                sed -i 's|^Exec=\(.*chromium[^ ]*\) |Exec=\1 --load-extension=/opt/elefante_blocker |g' "$DFILE" 2>/dev/null || true
                sed -i 's|^Exec=\(.*brave[^ ]*\) |Exec=\1 --load-extension=/opt/elefante_blocker |g' "$DFILE" 2>/dev/null || true
                sed -i 's|^Exec=\(.*edge[^ ]*\) |Exec=\1 --load-extension=/opt/elefante_blocker |g' "$DFILE" 2>/dev/null || true
                chmod 755 "$DFILE" 2>/dev/null || true
                U_NAME=$(echo "$DFILE" | awk -F/ '/^\/home\//{print $3}')
                if [ -n "$U_NAME" ]; then
                    U_GRP=$(id -gn "$U_NAME" 2>/dev/null || echo "$U_NAME")
                    chown "$U_NAME:$U_GRP" "$DFILE" 2>/dev/null || true
                    sudo -u "$U_NAME" gio set "$DFILE" metadata::trusted true 2>/dev/null || true
                    sudo -u "$U_NAME" gio set "$DFILE" metadata::trusted yes 2>/dev/null || true
                fi
            fi
        done

        # 4. Configurar flags de inicialização para os usuários (~/.config/*-flags.conf)
        for U_DIR in /home/* /etc/skel /root; do
            if [ -d "$U_DIR" ]; then
                mkdir -p "$U_DIR/.config" 2>/dev/null || true
                for CFG in chrome-flags.conf chromium-flags.conf brave-flags.conf google-chrome-flags.conf; do
                    touch "$U_DIR/.config/$CFG" 2>/dev/null || true
                    sed -i '/elefante_blocker/d' "$U_DIR/.config/$CFG" 2>/dev/null || true
                    echo "--load-extension=/opt/elefante_blocker" >> "$U_DIR/.config/$CFG"
                done
                U_OWNER=$(stat -c '%U:%G' "$U_DIR" 2>/dev/null || echo "root:root")
                chown -R "$U_OWNER" "$U_DIR/.config" 2>/dev/null || true
            fi
        done

        # 5. Políticas Corporativas Nativas URLBlocklist com sintaxe válida do Chromium
        for c_dir in /etc/chromium/policies/managed /etc/opt/chrome/policies/managed /etc/chrome/policies/managed /etc/google-chrome/policies/managed /etc/brave/policies/managed /etc/edge/policies/managed /etc/opt/edge/policies/managed /var/snap/chromium/current/policies/managed /etc/chromium-browser/policies/managed; do
            mkdir -p "$c_dir" 2>/dev/null || true
            cat << 'EOF' > "$c_dir/block_stickers.json"
{
  "URLBlocklist": [
    "mundoelefante.elefanteletrado.com.br",
    "stickers.elefanteletrado.com.br",
    "album.elefanteletrado.com.br",
    "api-stickers.elefanteletrado.com.br",
    "figurinhas.elefanteletrado.com.br",
    "perfil.elefanteletrado.com.br",
    "avatar.elefanteletrado.com.br",
    "mascote.elefanteletrado.com.br",
    "mascotes.elefanteletrado.com.br",
    "conquistas.elefanteletrado.com.br",
    "premios.elefanteletrado.com.br",
    "trofeus.elefanteletrado.com.br",
    "elefanteletrado.com.br/api/sticker",
    "elefanteletrado.com.br/api/stickers",
    "elefanteletrado.com.br/api/album",
    "elefanteletrado.com.br/api/figurinhas",
    "elefanteletrado.com.br/api/perfil",
    "elefanteletrado.com.br/api/profile",
    "elefanteletrado.com.br/api/avatar",
    "elefanteletrado.com.br/stickers",
    "elefanteletrado.com.br/album",
    "elefanteletrado.com.br/figurinhas",
    "elefanteletrado.com.br/perfil",
    "elefanteletrado.com.br/profile",
    "elefanteletrado.com.br/avatar"
  ]
}
EOF
            chmod 644 "$c_dir/block_stickers.json" 2>/dev/null || true
        done

        # 6. Políticas do Firefox
        mkdir -p /etc/firefox/policies /var/snap/firefox/current/distribution 2>/dev/null || true
        cat << 'EOF' > /etc/firefox/policies/policies.json
{
  "policies": {
    "URLBlocklist": [
      "mundoelefante.elefanteletrado.com.br",
      "stickers.elefanteletrado.com.br",
      "album.elefanteletrado.com.br",
      "api-stickers.elefanteletrado.com.br",
      "figurinhas.elefanteletrado.com.br",
      "perfil.elefanteletrado.com.br",
      "avatar.elefanteletrado.com.br",
      "mascote.elefanteletrado.com.br",
      "mascotes.elefanteletrado.com.br",
      "conquistas.elefanteletrado.com.br",
      "premios.elefanteletrado.com.br",
      "trofeus.elefanteletrado.com.br",
      "elefanteletrado.com.br/api/sticker",
      "elefanteletrado.com.br/api/stickers",
      "elefanteletrado.com.br/api/album",
      "elefanteletrado.com.br/api/figurinhas",
      "elefanteletrado.com.br/api/perfil",
      "elefanteletrado.com.br/api/profile",
      "elefanteletrado.com.br/api/avatar",
      "elefanteletrado.com.br/stickers",
      "elefanteletrado.com.br/album",
      "elefanteletrado.com.br/figurinhas",
      "elefanteletrado.com.br/perfil",
      "elefanteletrado.com.br/profile",
      "elefanteletrado.com.br/avatar"
    ]
  }
}
EOF
        for d in /usr/lib/firefox/distribution /usr/lib64/firefox/distribution /usr/share/firefox/distribution /var/snap/firefox/current/distribution; do
            mkdir -p "$d" 2>/dev/null || true
            cp -f /etc/firefox/policies/policies.json "$d/policies.json" 2>/dev/null || true
            chmod 644 "$d/policies.json" 2>/dev/null || true
        done

        # 7. Injetar userContent.css no Firefox com escopo explícito @-moz-document domain("elefanteletrado.com.br")
        cat << 'EOF' > /opt/elefante_blocker/userContent.css
@-moz-document domain("elefanteletrado.com.br") {
    a[href*="stickers"], a[href*="sticker"], a[href*="album"], a[href*="figurinhas"], a[href*="figurinha"], a[href*="mundoelefante"], a[href*="profile"], a[href*="perfil"], a[href*="avatar"],
    [ui-sref*="stickers"], [ui-sref*="sticker"], [ui-sref*="album"], [ui-sref*="figurinhas"], [ui-sref*="figurinha"], [ui-sref*="profile"], [ui-sref*="perfil"], [ui-sref*="avatar"],
    [data-ui-sref*="stickers"], [data-ui-sref*="sticker"], [data-ui-sref*="album"], [data-ui-sref*="figurinhas"], [data-ui-sref*="profile"], [data-ui-sref*="perfil"], [data-ui-sref*="avatar"],
    [ng-click*="sticker"], [ng-click*="Sticker"], [ng-click*="album"], [ng-click*="Album"], [ng-click*="figurinha"],
    [ng-click*="stickers"], [ng-click*="Stickers"], [ng-click*="figurinhas"], [ng-click*="profile"], [ng-click*="Profile"], [ng-click*="perfil"], [ng-click*="Perfil"], [ng-click*="avatar"],
    [routerlink*="sticker"], [routerlink*="album"], [routerlink*="figurinha"], [routerlink*="profile"], [routerlink*="perfil"],
    .menu-stickers, .menu-album, .menu-perfil, .nav-stickers, .nav-album, .profile-menu, .user-profile-btn, .profile-box, .avatar-box,
    [class*="sticker"], [class*="album"], [class*="figurinha"], [id*="sticker"], [id*="album"], [id*="figurinha"],
    [class*="profile"], [id*="profile"], [class*="perfil"], [id*="perfil"], [class*="avatar"], [id*="avatar"],
    img[src*="sticker"], img[src*="album"], img[src*="figurinha"], img[src*="avatar"] {
        display: none !important;
        pointer-events: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        max-height: 0 !important;
        max-width: 0 !important;
        overflow: hidden !important;
    }
}
EOF
        for U_DIR in /home/* /etc/skel /root; do
            if [ -d "$U_DIR" ]; then
                for FF_BASE in "$U_DIR/.mozilla/firefox" "$U_DIR/snap/firefox/common/.mozilla/firefox"; do
                    if [ -d "$FF_BASE" ]; then
                        for PROF_DIR in "$FF_BASE/"*; do
                            if [ -d "$PROF_DIR" ]; then
                                mkdir -p "$PROF_DIR/chrome"
                                sed -i '/toolkit.legacyUserProfileCustomizations.stylesheets/d' "$PROF_DIR/user.js" 2>/dev/null || true
                                echo 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);' >> "$PROF_DIR/user.js"
                                sed -i '/toolkit.legacyUserProfileCustomizations.stylesheets/d' "$PROF_DIR/prefs.js" 2>/dev/null || true
                                echo 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);' >> "$PROF_DIR/prefs.js"
                                cp -f /opt/elefante_blocker/userContent.css "$PROF_DIR/chrome/userContent.css" 2>/dev/null || true
                            fi
                        done
                    fi
                done
                U_OWNER=$(stat -c '%U:%G' "$U_DIR" 2>/dev/null || echo "root:root")
                chown -R "$U_OWNER" "$U_DIR/.mozilla" 2>/dev/null || true
            fi
        done

        # 8. Reiniciar instâncias abertas do Elefante Letrado para carregar a extensão imediatamente
        pkill -f "elefanteletrado" 2>/dev/null || true
        pkill -f "login.elefanteletrado" 2>/dev/null || true

        echo "✅ Bloqueio de Stickers e Meu Perfil ativado com sucesso exclusivamente para o Elefante Letrado!"
    """
    return script.strip(), None


@register_command('desbloquear_stickers', 'Desbloquear Stickers e Meu Perfil (Elefante Letrado)', 'Configurações de Rede', icon='check-circle')
def _build_unblock_stickers_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Desbloqueia o Álbum de Figurinhas/Stickers e o Meu Perfil do Elefante Letrado.
    Remove regras do /etc/hosts, políticas corporativas URLBlocklist, extensão e restaura configurações padrão.
    """
    script = """
        echo "Removendo bloqueio do Álbum de Figurinhas e Meu Perfil..."

        # 1. Remover entradas do /etc/hosts e flush do DNS
        sed -i '/# BEGIN BLOCK_STICKERS/,/# END BLOCK_STICKERS/d' /etc/hosts
        systemd-resolve --flush-caches 2>/dev/null || resolvectl flush-caches 2>/dev/null || /etc/init.d/nscd restart 2>/dev/null || killall -HUP dnsmasq 2>/dev/null || true

        # 2. Restaurar binários ELF nativos (caso existisse .real antigo)
        for B_ELF in /opt/google/chrome/chrome /usr/lib/chromium-browser/chromium-browser /usr/lib/chromium/chromium /opt/brave.com/brave/brave /opt/microsoft/msedge/msedge; do
            B_DIR=$(dirname "$B_ELF")
            B_BASE=$(basename "$B_ELF")
            REAL_ELF="$B_DIR/${B_BASE}.real"
            if [ -f "$REAL_ELF" ]; then
                cp -p "$REAL_ELF" "$B_ELF" 2>/dev/null || true
                rm -f "$REAL_ELF" 2>/dev/null || true
                chmod 755 "$B_ELF" 2>/dev/null || true
            fi
        done

        # 3. Remover políticas corporativas de URLBlocklist do Elefante Letrado
        for c_dir in /etc/chromium/policies/managed /etc/opt/chrome/policies/managed /etc/chrome/policies/managed /etc/google-chrome/policies/managed /etc/brave/policies/managed /etc/edge/policies/managed /etc/opt/edge/policies/managed /var/snap/chromium/current/policies/managed /etc/chromium-browser/policies/managed; do
            rm -f "$c_dir/block_stickers.json" 2>/dev/null || true
        done
        rm -f /etc/firefox/policies/policies.json 2>/dev/null || true
        rm -f /usr/lib*/firefox/distribution/policies.json 2>/dev/null || true
        rm -f /usr/share/firefox/distribution/policies.json 2>/dev/null || true
        rm -f /var/snap/firefox/current/distribution/policies.json 2>/dev/null || true

        # 4. Remover arquivos da extensão
        rm -rf /opt/elefante_blocker /etc/elefante_blocker 2>/dev/null || true

        # 5. Limpar userContent.css do Firefox e flags dos usuários
        for U_DIR in /home/* /etc/skel /root; do
            if [ -d "$U_DIR" ]; then
                for FF_BASE in "$U_DIR/.mozilla/firefox" "$U_DIR/snap/firefox/common/.mozilla/firefox"; do
                    if [ -d "$FF_BASE" ]; then
                        for PROF_DIR in "$FF_BASE/"*; do
                            if [ -d "$PROF_DIR" ]; then
                                rm -f "$PROF_DIR/chrome/userContent.css" 2>/dev/null || true
                            fi
                        done
                    fi
                done
                if [ -d "$U_DIR/.config" ]; then
                    for CFG in chrome-flags.conf chromium-flags.conf brave-flags.conf google-chrome-flags.conf; do
                        if [ -f "$U_DIR/.config/$CFG" ]; then
                            sed -i '/elefante_blocker/d' "$U_DIR/.config/$CFG" 2>/dev/null || true
                        fi
                    done
                fi
            fi
        done

        # 6. Limpar flags dos atalhos .desktop
        find /usr/share/applications /usr/local/share/applications /home /etc/skel /root /etc/xdg/autostart /var/lib/snapd/desktop/applications -name "*.desktop" 2>/dev/null | while read -r DFILE; do
            if grep -qi "elefante" "$DFILE"; then
                sed -i 's| --load-extension=[^ "]*||g' "$DFILE" 2>/dev/null || true
                chmod 755 "$DFILE" 2>/dev/null || true
                U_NAME=$(echo "$DFILE" | awk -F/ '/^\/home\//{print $3}')
                if [ -n "$U_NAME" ]; then
                    U_GRP=$(id -gn "$U_NAME" 2>/dev/null || echo "$U_NAME")
                    chown "$U_NAME:$U_GRP" "$DFILE" 2>/dev/null || true
                    sudo -u "$U_NAME" gio set "$DFILE" metadata::trusted true 2>/dev/null || true
                fi
            fi
        done

        # 7. Reiniciar instâncias abertas do Elefante Letrado para liberar normalmente
        pkill -f "elefanteletrado" 2>/dev/null || true
        pkill -f "login.elefanteletrado" 2>/dev/null || true

        echo "✅ Desbloqueio de Stickers e Meu Perfil concluído com sucesso!"
    """
    return script.strip(), None


@register_command('ativar_protecao_total_infantil', '🛡️ Ativar Proteção Total Infantil (Master)', 'Configurações de Rede', icon='shield', is_streaming=True)
def _build_master_child_protection(data: Dict[str, Any]) -> Tuple[str, None]:

    """
    Executa a ativação combinada de TODAS as camadas de proteção infantil em um único script rápido:
    1. Configura DNS Cloudflare Family (1.1.1.3).
    2. Ativa SafeSearch no Google, Bing e Modo Restrito no YouTube.
    3. Bloqueia Redes Sociais, Discord e Chatbots de IA.
    4. Bloqueia Web Proxies e VPNs.
    5. Desativa e trava DNS-over-HTTPS (DoH) nos navegadores.
    6. Encerra aplicativos de IA em execução (Ollama, ChatGPT, etc.).
    7. Ativa Modo Kiosk Infantil Fullscreen com persistência em aberturas manuais.
    """
    raw_url = data.get('whitelist_sites', '').strip() or data.get('sites', '').strip() or data.get('url', '').strip() or 'https://www.google.com'
    first_url = raw_url.split()[0] if raw_url else 'https://www.google.com'
    if not first_url.startswith(('http://', 'https://')):
        first_url = 'https://' + first_url

    safe_url = shlex.quote(first_url)

    social_domains = SITE_CATEGORIES_CONFIG.get('redes_sociais', {}).get('domains', [])
    ai_domains = SITE_CATEGORIES_CONFIG.get('chatbots_ia', {}).get('domains', [])
    proxy_domains = SITE_CATEGORIES_CONFIG.get('proxies_e_vpns', {}).get('domains', [])

    all_blocked_domains = sorted(list(set(social_domains + ai_domains + proxy_domains)))

    hosts_entries = []
    dnsmasq_entries = []
    for domain in all_blocked_domains:
        hosts_entries.append(f"127.0.0.1 {domain}")
        dnsmasq_entries.append(f"address=/{domain}/127.0.0.1")
        if not domain.startswith('www.'):
            hosts_entries.append(f"127.0.0.1 www.{domain}")
            dnsmasq_entries.append(f"address=/www.{domain}/127.0.0.1")

    hosts_content = "\n".join(hosts_entries)
    dnsmasq_content = "\n".join(dnsmasq_entries)

    procs_str = " ".join([shlex.quote(p) for p in AI_APPLICATION_PROCESSES if p.strip()])

    script = f"""
        {GSETTINGS_ENV_SETUP}

        echo "🛡️ --- INICIANDO ATIVAÇÃO DA PROTEÇÃO TOTAL INFANTIL ---"
        sudo touch /etc/child_protection_active 2>/dev/null || true

        # 1. Configura DNS Cloudflare Family (1.1.1.3 / 1.0.0.3)
        echo "[1/7] Configurando DNS Cloudflare Family (1.1.1.3 / 1.0.0.3)..."
        for np_file in /etc/netplan/*.yaml; do
            if [ -f "$np_file" ]; then
                sudo sed -i 's/addresses: \\[\\(.*\\)\\]/addresses: [1.1.1.3, 1.0.0.3]/' "$np_file" 2>/dev/null || true
                sudo netplan apply 2>/dev/null || true
            fi
        done
        if [ -f /etc/resolv.conf ]; then
            sudo sed -i '/nameserver/d' /etc/resolv.conf 2>/dev/null || true
            echo "nameserver 1.1.1.3" | sudo tee -a /etc/resolv.conf > /dev/null
            echo "nameserver 1.0.0.3" | sudo tee -a /etc/resolv.conf > /dev/null
        fi

        # 2. Configura SafeSearch (Google, Bing, YouTube) via /etc/hosts
        echo "[2/7] Ativando SafeSearch no Google, Bing e Modo Restrito no YouTube..."
        sudo sed -i '/# BEGIN SAFESEARCH/,/# END SAFESEARCH/d' /etc/hosts
        cat << 'EOF' | sudo tee -a /etc/hosts > /dev/null

# BEGIN SAFESEARCH
216.239.38.120 google.com
216.239.38.120 www.google.com
216.239.38.120 forcesafesearch.google.com
216.239.38.120 restrict.youtube.com
216.239.38.120 youtube.com
216.239.38.120 www.youtube.com
216.239.38.120 m.youtube.com
204.79.197.220 bing.com
204.79.197.220 www.bing.com
204.79.197.220 strict.bing.com
52.142.124.215 duckduckgo.com
52.142.124.215 safe.duckduckgo.com
# END SAFESEARCH
EOF

        # 3. Aplica bloqueio de Redes Sociais, IA, Proxies e VPNs no /etc/hosts e dnsmasq
        echo "[3/7] Aplicando bloqueio de Redes Sociais, IA, Proxies e VPNs ({len(all_blocked_domains)} domínios)..."
        sudo sed -i '/# BEGIN BLOCK_CHILD_PROTECTION/,/# END BLOCK_CHILD_PROTECTION/d' /etc/hosts
        cat << 'EOF' | sudo tee -a /etc/hosts > /dev/null

# BEGIN BLOCK_CHILD_PROTECTION
{hosts_content}
# END BLOCK_CHILD_PROTECTION
EOF

        if [ -d /etc/dnsmasq.d ]; then
            cat << 'EOF' | sudo tee /etc/dnsmasq.d/block_child_protection.conf > /dev/null
# Bloqueio de Redes Sociais, IA, Proxies e VPNs
{dnsmasq_content}
EOF
            if systemctl is-active --quiet dnsmasq; then
                sudo systemctl restart dnsmasq || true
            fi
        fi

        # 4. Configura Políticas Enterprise nos Navegadores (F12, DevTools, DoH off, Kiosk)
        echo "[4/7] Configurando Políticas Enterprise nos Navegadores (DoH off, DevTools off)..."
        sudo mkdir -p /etc/chromium/policies/managed \\
                     /etc/opt/chrome/policies/managed \\
                     /etc/brave/policies/managed \\
                     /etc/brave-browser/policies/managed \\
                     /etc/opt/edge/policies/managed \\
                     /etc/opera/policies/managed

        cat << 'EOF' | sudo tee /etc/chromium/policies/managed/kiosk_child_policy.json > /dev/null
{{
  "DeveloperToolsAvailability": 2,
  "IncognitoModeAvailability": 1,
  "PasswordManagerEnabled": false,
  "AutofillAddressEnabled": false,
  "AutofillCreditCardEnabled": false,
  "DownloadRestrictions": 3,
  "ExtensionInstallBlocklist": ["*"],
  "DefaultPopupsSetting": 2,
  "SafeBrowsingProtectionLevel": 2,
  "MetricsReportingEnabled": false,
  "BrowserAddPersonEnabled": false,
  "DnsOverHttpsMode": "off",
  "DnsOverHttpsTemplates": ""
}}
EOF

        for d in /etc/opt/chrome/policies/managed \\
                 /etc/brave/policies/managed \\
                 /etc/brave-browser/policies/managed \\
                 /etc/opt/edge/policies/managed \\
                 /etc/opera/policies/managed; do
            sudo cp /etc/chromium/policies/managed/kiosk_child_policy.json "$d/" 2>/dev/null || true
        done

        sudo mkdir -p /etc/firefox/policies \\
                     /usr/lib/firefox/distribution \\
                     /usr/lib64/firefox/distribution \\
                     /usr/share/firefox/distribution 2>/dev/null || true

        cat << 'EOF' | sudo tee /etc/firefox/policies/policies.json > /dev/null
{{
  "policies": {{
    "DisableDeveloperTools": true,
    "DisableFirefoxAccounts": true,
    "DisablePrivateBrowsing": true,
    "BlockAboutConfig": true,
    "BlockAboutProfiles": true,
    "BlockAboutSupport": true,
    "OfferToSaveLogins": false,
    "PasswordManagerEnabled": false,
    "DNSOverHTTPS": {{
      "Enabled": false,
      "Locked": true
    }},
    "ExtensionSettings": {{
      "*": {{
        "installation_mode": "blocked"
      }}
    }}
  }}
}}
EOF

        for d in /usr/lib/firefox/distribution /usr/lib64/firefox/distribution /usr/share/firefox/distribution; do
            if [ -d "$(dirname "$d")" ]; then
                sudo cp /etc/firefox/policies/policies.json "$d/" 2>/dev/null || true
            fi
        done

        # 5. Finaliza Processos Nocivos de IA
        echo "[5/7] Encerrando processos locais de IA (Ollama, ChatGPT, etc)..."
        PROCS=({procs_str})
        MY_PID=$$
        MY_PPID=$PPID
        for proc in "${{PROCS[@]}}"; do
            if [ -n "$proc" ]; then
                PIDS=$(pgrep -f "$proc" 2>/dev/null || true)
                for pid in $PIDS; do
                    if [ "$pid" != "$MY_PID" ] && [ "$pid" != "$MY_PPID" ]; then
                        p_cmd=$(ps -p "$pid" -o cmd= 2>/dev/null || true)
                        if [[ "$p_cmd" != *"sudo -S"* ]] && [[ "$p_cmd" != *"PROCS="* ]] && [[ "$p_cmd" != *"pgrep"* ]]; then
                            kill -9 "$pid" 2>/dev/null || true
                        fi
                    fi
                done
            fi
        done

        # 6. Cria Wrappers de Persistência para Atalhos e Aberturas Manuais
        echo "[6/7] Criando wrappers de persistência para atalhos e aberturas manuais..."
        for b in google-chrome google-chrome-stable chromium-browser chromium brave-browser microsoft-edge-stable msedge opera; do
            real_bin=$(which -a "$b" 2>/dev/null | grep -v "/usr/local/bin" | head -n1)
            if [ -n "$real_bin" ] && [ -x "$real_bin" ]; then
                sudo tee "/usr/local/bin/$b" > /dev/null << EOF
#!/bin/bash
TARGET_URL={safe_url}

for arg in "\$@"; do
    clean_arg="\${{arg#--app=}}"

    if [[ "\$clean_arg" == *.desktop ]] && [ -f "\$clean_arg" ]; then
        url_in_file=\$(grep -E '^URL=' "\$clean_arg" 2>/dev/null | cut -d'=' -f2-)
        if [ -z "\$url_in_file" ]; then
            url_in_file=\$(grep -E '^Exec=' "\$clean_arg" 2>/dev/null | sed -E 's/^Exec=[^ ]+ //; s/ %U//; s/ %u//; s/--app=//')
        fi
        if [ -n "\$url_in_file" ]; then
            clean_arg="\$url_in_file"
        fi
    fi

    if [[ "\$clean_arg" == http://* ]] || [[ "\$clean_arg" == https://* ]] || [[ "\$clean_arg" == www.* ]] || [[ "\$clean_arg" == *matific* ]] || [[ "\$clean_arg" == *.com* ]] || [[ "\$clean_arg" == *.br* ]]; then
        if [[ "\$clean_arg" == www.* ]] || [[ "\$clean_arg" == matific.* ]]; then
            TARGET_URL="https://\$clean_arg"
        else
            TARGET_URL="\$clean_arg"
        fi
    elif [[ "\$clean_arg" != %* ]] && [[ "\$clean_arg" != --* ]] && [ -n "\$clean_arg" ]; then
        TARGET_URL="\$clean_arg"
    fi
done

if [[ "\$TARGET_URL" != http://* ]] && [[ "\$TARGET_URL" != https://* ]] && [[ "\$TARGET_URL" != /* ]]; then
    TARGET_URL="https://\$TARGET_URL"
fi

exec "$real_bin" --kiosk --no-sandbox --no-first-run --disable-context-menu --disable-pinch --overscroll-history-navigation=0 --disable-translate --no-default-browser-check "\$TARGET_URL"
EOF
                sudo chmod 755 "/usr/local/bin/$b"
            fi
        done

        firefox_real=$(which -a firefox 2>/dev/null | grep -v "/usr/local/bin" | head -n1)
        if [ -n "$firefox_real" ] && [ -x "$firefox_real" ]; then
            sudo tee "/usr/local/bin/firefox" > /dev/null << EOF
#!/bin/bash
TARGET_URL={safe_url}

for arg in "\$@"; do
    clean_arg="\${{arg#--app=}}"
    if [[ "\$clean_arg" == *.desktop ]] && [ -f "\$clean_arg" ]; then
        url_in_file=\$(grep -E '^URL=' "\$clean_arg" 2>/dev/null | cut -d'=' -f2-)
        [ -n "\$url_in_file" ] && clean_arg="\$url_in_file"
    fi
    if [[ "\$clean_arg" == http://* ]] || [[ "\$clean_arg" == https://* ]] || [[ "\$clean_arg" == www.* ]] || [[ "\$clean_arg" == *matific* ]] || [[ "\$clean_arg" == *.com* ]] || [[ "\$clean_arg" == *.br* ]]; then
        TARGET_URL="\$clean_arg"
    fi
done

if [[ "\$TARGET_URL" != http://* ]] && [[ "\$TARGET_URL" != https://* ]] && [[ "\$TARGET_URL" != /* ]]; then
    TARGET_URL="https://\$TARGET_URL"
fi

exec "$firefox_real" --kiosk "\$TARGET_URL"
EOF
            sudo chmod 755 "/usr/local/bin/firefox"
        fi

        # 7. Bloqueia atalhos do sistema (Alt+F4, Alt+Tab) e lança Modo Kiosk
        echo "[7/7] Bloqueando atalhos de janelas do sistema (Alt+F4, Alt+Tab) e iniciando Modo Kiosk..."
        gsettings set org.gnome.desktop.wm.keybindings close "[]" 2>/dev/null || true
        gsettings set org.gnome.desktop.wm.keybindings switch-applications "[]" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm close "[]" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm switch-applications "[]" 2>/dev/null || true

        pkill -x google-chrome 2>/dev/null || true
        pkill -x chrome 2>/dev/null || true
        pkill -x chromium-browser 2>/dev/null || true
        pkill -x chromium 2>/dev/null || true
        pkill -x brave 2>/dev/null || true
        pkill -x brave-browser 2>/dev/null || true
        pkill -x msedge 2>/dev/null || true
        pkill -x opera 2>/dev/null || true
        pkill -x firefox 2>/dev/null || true
        sleep 1

        LOGGED_USER=$(who | grep -E '(:0|tty|x11)' | awk '{{print $1}}' | head -n1)
        [ -z "$LOGGED_USER" ] && LOGGED_USER=$(who | awk '{{print $1}}' | head -n1)
        [ -z "$LOGGED_USER" ] && LOGGED_USER="aluno"

        USER_ID=$(id -u "$LOGGED_USER" 2>/dev/null || echo 1000)
        export DISPLAY=${{DISPLAY:-:0}}
        
        XAUTH_CANDIDATE=""
        for f in "/run/user/$USER_ID/gdm/Xauthority" "/run/user/$USER_ID/.mutter-Xwayland-Xauthority" "/home/$LOGGED_USER/.Xauthority"; do
            if [ -f "$f" ]; then
                XAUTH_CANDIDATE="$f"
                break
            fi
        done
        [ -n "$XAUTH_CANDIDATE" ] && export XAUTHORITY="$XAUTH_CANDIDATE"

        LAUNCH_BIN=""
        if command -v google-chrome &> /dev/null; then LAUNCH_BIN="google-chrome"
        elif command -v chromium-browser &> /dev/null; then LAUNCH_BIN="chromium-browser"
        elif command -v chromium &> /dev/null; then LAUNCH_BIN="chromium"
        elif command -v brave-browser &> /dev/null; then LAUNCH_BIN="brave-browser"
        elif command -v microsoft-edge-stable &> /dev/null; then LAUNCH_BIN="microsoft-edge-stable"
        elif command -v opera &> /dev/null; then LAUNCH_BIN="opera"
        elif command -v firefox &> /dev/null; then LAUNCH_BIN="firefox"
        fi

        if [ -n "$LAUNCH_BIN" ]; then
            if [ "$LAUNCH_BIN" = "firefox" ]; then K_ARGS="--kiosk {safe_url}"
            else K_ARGS="--kiosk --no-sandbox --no-first-run --disable-context-menu --disable-pinch --overscroll-history-navigation=0 --disable-translate --no-default-browser-check {safe_url}"
            fi

            if [ "$LOGGED_USER" != "root" ] && id "$LOGGED_USER" &>/dev/null; then
                sudo -u "$LOGGED_USER" DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" nohup $LAUNCH_BIN $K_ARGS </dev/null >/dev/null 2>&1 &
            else
                nohup $LAUNCH_BIN $K_ARGS </dev/null >/dev/null 2>&1 &
            fi
        fi

        if systemctl is-active --quiet systemd-resolved; then
            sudo systemd-resolve --flush-caches 2>/dev/null || sudo resolvectl flush-caches 2>/dev/null || true
        fi

        echo "✅ ✅ PROTEÇÃO TOTAL INFANTIL ATIVADA COM SUCESSO EM TODAS AS MÁQUINAS!"
    """
    return script.strip(), None

@register_command('desativar_protecao_total_infantil', '🔓 Remover Proteção Total Infantil (Master)', 'Configurações de Rede', icon='shield-off', is_streaming=True)
def _build_disable_master_child_protection(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Remove TODAS as restrições e camadas de proteção infantil de uma só vez:
    1. Desativa o Modo Kiosk e restaura os navegadores padrão.
    2. Remove bloqueios de Redes Sociais, IA, Proxies e VPNs no /etc/hosts e dnsmasq.
    3. Remove SafeSearch do Google, Bing e YouTube.
    4. Remove políticas Enterprise corporativas (DoH off, DevTools off).
    5. Restaura os atalhos do sistema (Alt+F4, Alt+Tab).
    6. Limpa o cache DNS.
    """
    script = """
        echo "🔓 --- REMOVENDO PROTEÇÃO TOTAL INFANTIL ---"
        sudo rm -f /etc/child_protection_active 2>/dev/null || true

        # 1. Remove wrappers de persistência em /usr/local/bin
        echo "[1/5] Removendo wrappers de persistência e restaurando navegadores..."
        for b in google-chrome google-chrome-stable chromium-browser chromium brave-browser microsoft-edge-stable msedge opera firefox; do
            if [ -f "/usr/local/bin/$b" ]; then
                sudo rm -f "/usr/local/bin/$b"
            fi
        done

        # 2. Remove políticas Enterprise corporativas dos navegadores
        echo "[2/5] Removendo Políticas Enterprise dos navegadores..."
        sudo rm -f /etc/chromium/policies/managed/kiosk_child_policy.json \
                     /etc/opt/chrome/policies/managed/kiosk_child_policy.json \
                     /etc/brave/policies/managed/kiosk_child_policy.json \
                     /etc/brave-browser/policies/managed/kiosk_child_policy.json \
                     /etc/opt/edge/policies/managed/kiosk_child_policy.json \
                     /etc/opera/policies/managed/kiosk_child_policy.json \
                     /etc/chromium/policies/managed/disable_doh.json \
                     /etc/opt/chrome/policies/managed/disable_doh.json \
                     /etc/brave/policies/managed/disable_doh.json \
                     /etc/brave-browser/policies/managed/disable_doh.json \
                     /etc/opt/edge/policies/managed/disable_doh.json \
                     /etc/opera/policies/managed/disable_doh.json \
                     /etc/firefox/policies/policies.json \
                     /usr/lib/firefox/distribution/policies.json \
                     /usr/lib64/firefox/distribution/policies.json \
                     /usr/share/firefox/distribution/policies.json 2>/dev/null || true

        # 3. Remove bloqueios de hosts, SafeSearch, Redes Sociais, IA, Proxies e VPNs
        echo "[3/5] Removendo bloqueios de sites, redes sociais, IA, proxies, VPNs e SafeSearch..."
        sudo sed -i '/# BEGIN SAFESEARCH/,/# END SAFESEARCH/d' /etc/hosts
        sudo sed -i '/# BEGIN BLOCK_CHILD_PROTECTION/,/# END BLOCK_CHILD_PROTECTION/d' /etc/hosts
        sudo sed -i '/# BEGIN BLOCK_SOCIAL_AI/,/# END BLOCK_SOCIAL_AI/d' /etc/hosts
        sudo sed -i '/# BEGIN BLOCK_PROXIES_VPN/,/# END BLOCK_PROXIES_VPN/d' /etc/hosts

        if [ -f /etc/dnsmasq.d/block_child_protection.conf ]; then
            sudo rm -f /etc/dnsmasq.d/block_child_protection.conf
        fi
        if [ -f /etc/dnsmasq.d/block_social_ai.conf ]; then
            sudo rm -f /etc/dnsmasq.d/block_social_ai.conf
        fi
        if [ -f /etc/dnsmasq.d/block_proxies_vpn.conf ]; then
            sudo rm -f /etc/dnsmasq.d/block_proxies_vpn.conf
        fi

        if systemctl is-active --quiet dnsmasq; then
            sudo systemctl restart dnsmasq || true
        fi

        # 4. Restaura atalhos de janela do sistema (Alt+F4, Alt+Tab)
        echo "[4/5] Restaurando atalhos do sistema (Alt+F4, Alt+Tab)..."
        gsettings set org.gnome.desktop.wm.keybindings close "['<Alt>F4']" 2>/dev/null || true
        gsettings set org.gnome.desktop.wm.keybindings switch-applications "['<Alt>Tab']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm close "['<Alt>F4']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm switch-applications "['<Alt>Tab']" 2>/dev/null || true

        # 5. Encerra processos Kiosk e limpa cache DNS
        echo "[5/5] Encerrando instâncias em Modo Kiosk e limpando cache DNS..."
        pkill -x google-chrome 2>/dev/null || true
        pkill -x chrome 2>/dev/null || true
        pkill -x chromium-browser 2>/dev/null || true
        pkill -x chromium 2>/dev/null || true
        pkill -x brave 2>/dev/null || true
        pkill -x brave-browser 2>/dev/null || true
        pkill -x msedge 2>/dev/null || true
        pkill -x opera 2>/dev/null || true
        pkill -x firefox 2>/dev/null || true

        if systemctl is-active --quiet systemd-resolved; then
            sudo systemd-resolve --flush-caches 2>/dev/null || sudo resolvectl flush-caches 2>/dev/null || true
        fi

        echo "✅ ✅ PROTEÇÃO TOTAL INFANTIL REMOVIDA COM SUCESSO! MÁQUINAS RESTAURADAS."
    """
    return script.strip(), None

@register_command('bloquear_proxies_e_vpns', 'Bloquear Proxies Web & VPNs', 'Configurações de Rede', icon='shield')
def _build_block_proxies_and_vpns(data: Dict[str, Any]) -> Tuple[str, None]:
    """Bloqueia o acesso a Proxies Web e serviços de VPN via /etc/hosts e dnsmasq."""
    proxy_domains = SITE_CATEGORIES_CONFIG.get('proxies_e_vpns', {}).get('domains', [])
    all_domains = sorted(list(set(proxy_domains)))
    
    hosts_entries = []
    dnsmasq_entries = []
    
    for domain in all_domains:
        hosts_entries.append(f"127.0.0.1 {domain}")
        dnsmasq_entries.append(f"address=/{domain}/127.0.0.1")
        if not domain.startswith('www.'):
            hosts_entries.append(f"127.0.0.1 www.{domain}")
            dnsmasq_entries.append(f"address=/www.{domain}/127.0.0.1")

    hosts_content = "\n".join(hosts_entries)
    dnsmasq_content = "\n".join(dnsmasq_entries)

    script = f"""
        echo "Aplicando bloqueio de Proxies Web e VPNs..."

        sudo sed -i '/# BEGIN BLOCK_PROXIES_VPN/,/# END BLOCK_PROXIES_VPN/d' /etc/hosts

        cat << 'EOF' | sudo tee -a /etc/hosts > /dev/null

# BEGIN BLOCK_PROXIES_VPN
{hosts_content}
# END BLOCK_PROXIES_VPN
EOF

        if [ -d /etc/dnsmasq.d ]; then
            cat << 'EOF' | sudo tee /etc/dnsmasq.d/block_proxies_vpn.conf > /dev/null
# Bloqueio de Proxies Web e VPNs
{dnsmasq_content}
EOF
            if systemctl is-active --quiet dnsmasq; then
                sudo systemctl restart dnsmasq || true
            fi
        fi

        if systemctl is-active --quiet systemd-resolved; then
            sudo systemd-resolve --flush-caches 2>/dev/null || sudo resolvectl flush-caches 2>/dev/null || true
        fi

        echo "✅ Bloqueio de Proxies Web e VPNs aplicado com sucesso ({len(all_domains)} domínios bloqueados)."
    """
    return script.strip(), None

@register_command('desbloquear_proxies_e_vpns', 'Remover Bloqueio de Proxies Web & VPNs', 'Configurações de Rede', icon='shield-off')
def _build_unblock_proxies_and_vpns(data: Dict[str, Any]) -> Tuple[str, None]:
    """Remove o bloqueio de Proxies Web e VPNs."""
    script = """
        echo "Removendo bloqueio de Proxies Web e VPNs..."

        sudo sed -i '/# BEGIN BLOCK_PROXIES_VPN/,/# END BLOCK_PROXIES_VPN/d' /etc/hosts

        if [ -f /etc/dnsmasq.d/block_proxies_vpn.conf ]; then
            sudo rm -f /etc/dnsmasq.d/block_proxies_vpn.conf
            if systemctl is-active --quiet dnsmasq; then
                sudo systemctl restart dnsmasq || true
            fi
        fi

        if systemctl is-active --quiet systemd-resolved; then
            sudo systemd-resolve --flush-caches 2>/dev/null || sudo resolvectl flush-caches 2>/dev/null || true
        fi

        echo "✅ Bloqueio de Proxies Web e VPNs REMOVIDO."
    """
    return script.strip(), None

@register_command('desativar_doh_navegadores', 'Desativar DNS-over-HTTPS (DoH)', 'Configurações do Navegador', icon='lock')
def _build_disable_doh_browsers(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Força a desativação do DNS-over-HTTPS (DoH) no Chrome, Chromium, Brave, Edge, Opera e Firefox
    para impedir que alunos burlem o DNS local ou /etc/hosts via DNS criptografado.
    """
    script = """
        echo "Desativando DNS-over-HTTPS (DoH) em todos os navegadores..."

        sudo mkdir -p /etc/chromium/policies/managed \
                     /etc/opt/chrome/policies/managed \
                     /etc/brave/policies/managed \
                     /etc/brave-browser/policies/managed \
                     /etc/opt/edge/policies/managed \
                     /etc/opera/policies/managed

        cat << 'EOF' | sudo tee /etc/chromium/policies/managed/disable_doh.json > /dev/null
{
  "DnsOverHttpsMode": "off",
  "DnsOverHttpsTemplates": ""
}
EOF

        for d in /etc/opt/chrome/policies/managed \
                 /etc/brave/policies/managed \
                 /etc/brave-browser/policies/managed \
                 /etc/opt/edge/policies/managed \
                 /etc/opera/policies/managed; do
            sudo cp /etc/chromium/policies/managed/disable_doh.json "$d/" 2>/dev/null || true
        done

        sudo mkdir -p /etc/firefox/policies \
                     /usr/lib/firefox/distribution \
                     /usr/lib64/firefox/distribution \
                     /usr/share/firefox/distribution 2>/dev/null || true

        cat << 'EOF' | sudo tee /etc/firefox/policies/policies.json > /dev/null
{
  "policies": {
    "DNSOverHTTPS": {
      "Enabled": false,
      "Locked": true
    }
  }
}
EOF

        for d in /usr/lib/firefox/distribution /usr/lib64/firefox/distribution /usr/share/firefox/distribution; do
            if [ -d "$(dirname "$d")" ]; then
                sudo cp /etc/firefox/policies/policies.json "$d/" 2>/dev/null || true
            fi
        done

        echo "✅ DNS-over-HTTPS (DoH) desativado e travado em todos os navegadores."
    """
    return script.strip(), None

@register_command('ativar_doh_navegadores', 'Permitir DNS-over-HTTPS (DoH)', 'Configurações do Navegador', icon='unlock')
def _build_enable_doh_browsers(data: Dict[str, Any]) -> Tuple[str, None]:
    """Remove o bloqueio de DoH dos navegadores."""
    script = """
        echo "Removendo política de desativação do DNS-over-HTTPS..."
        sudo rm -f /etc/chromium/policies/managed/disable_doh.json
        sudo rm -f /etc/opt/chrome/policies/managed/disable_doh.json
        sudo rm -f /etc/brave/policies/managed/disable_doh.json
        sudo rm -f /etc/brave-browser/policies/managed/disable_doh.json
        sudo rm -f /etc/opt/edge/policies/managed/disable_doh.json
        sudo rm -f /etc/opera/policies/managed/disable_doh.json
        echo "✅ DNS-over-HTTPS (DoH) restaurado para o padrão."
    """
    return script.strip(), None

@register_command('encerrar_apps_ia', 'Encerrar Processos de IA (Ollama, ChatGPT, etc.)', 'Gerenciamento de Processos', icon='x-circle')
def _build_kill_ai_apps(data: Dict[str, Any]) -> Tuple[str, None]:
    """Procura e encerra qualquer aplicativo ou processo de IA em execução na máquina cliente."""
    procs_str = " ".join([shlex.quote(p) for p in AI_APPLICATION_PROCESSES if p.strip()])
    
    script = f"""
        echo "--- VERIFICANDO E ENCERRANDO APLICATIVOS DE IA ---"
        PROCS=({procs_str})
        KILLED=0
        MY_PID=$$
        MY_PPID=$PPID

        for proc in "${{PROCS[@]}}"; do
            if [ -n "$proc" ]; then
                PIDS=$(pgrep -f "$proc" 2>/dev/null || true)
                for pid in $PIDS; do
                    if [ "$pid" != "$MY_PID" ] && [ "$pid" != "$MY_PPID" ]; then
                        p_cmd=$(ps -p "$pid" -o cmd= 2>/dev/null || true)
                        if [[ "$p_cmd" != *"sudo -S"* ]] && [[ "$p_cmd" != *"PROCS="* ]] && [[ "$p_cmd" != *"pgrep"* ]]; then
                            echo "🛑 Finalizando processo detectado (PID $pid): $proc"
                            kill -9 "$pid" 2>/dev/null || true
                            KILLED=$((KILLED + 1))
                        fi
                    fi
                done
            fi
        done

        if [ "$KILLED" -eq 0 ]; then
            echo "✅ Nenhum processo ou aplicativo de IA ativo foi encontrado."
        else
            echo "✅ Total de $KILLED processo(s) de IA finalizado(s) com sucesso."
        fi
    """
    return script.strip(), None

@register_command('ativar_modo_kiosk_infantil', 'Ativar Modo Kiosk Infantil (Fullscreen)', 'Configurações do Navegador', icon='maximize-2', is_streaming=True)
def _build_enable_kiosk_mode(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Ativa o Modo Kiosk Infantil de alta segurança universal para TODOS os navegadores:
    Google Chrome, Chromium, Brave, Microsoft Edge, Opera e Mozilla Firefox.
    - Força tela cheia sem barra de endereços (--kiosk).
    - Persiste o Modo Kiosk mesmo se o navegador for aberto manualmente pelos atalhos/menu.
    - Desativa Developer Tools (F12, Ctrl+Shift+I, Inspect Element).
    - Desativa Menu de Contexto (botão direito) no navegador.
    - Desativa atalhos de janelas (Alt+F4, Alt+Tab, etc.) via gsettings.
    - Desativa downloads de arquivos perigosos e instalação de extensões em todos os navegadores.
    """
    raw_url = data.get('whitelist_sites', '').strip() or data.get('sites', '').strip() or data.get('url', '').strip() or 'https://www.google.com'
    first_url = raw_url.split()[0] if raw_url else 'https://www.google.com'
    if not first_url.startswith(('http://', 'https://')):
        first_url = 'https://' + first_url

    safe_url = shlex.quote(first_url)

    script = f"""
        {GSETTINGS_ENV_SETUP}

        echo "Configurando Políticas Enterprise Universais (Chrome, Chromium, Brave, Edge, Opera, Firefox)..."

        # 1. Cria diretórios de políticas para todos os navegadores da família Chromium
        sudo mkdir -p /etc/chromium/policies/managed \
                     /etc/opt/chrome/policies/managed \
                     /etc/brave/policies/managed \
                     /etc/brave-browser/policies/managed \
                     /etc/opt/edge/policies/managed \
                     /etc/opera/policies/managed

        # 2. Escreve política JSON estrita para a família Chromium
        cat << 'EOF' | sudo tee /etc/chromium/policies/managed/kiosk_child_policy.json > /dev/null
{{
  "DeveloperToolsAvailability": 2,
  "IncognitoModeAvailability": 1,
  "PasswordManagerEnabled": false,
  "AutofillAddressEnabled": false,
  "AutofillCreditCardEnabled": false,
  "DownloadRestrictions": 3,
  "ExtensionInstallBlocklist": ["*"],
  "DefaultPopupsSetting": 2,
  "SafeBrowsingProtectionLevel": 2,
  "MetricsReportingEnabled": false,
  "BrowserAddPersonEnabled": false,
  "DnsOverHttpsMode": "off",
  "DnsOverHttpsTemplates": ""
}}
EOF

        for d in /etc/opt/chrome/policies/managed \
                 /etc/brave/policies/managed \
                 /etc/brave-browser/policies/managed \
                 /etc/opt/edge/policies/managed \
                 /etc/opera/policies/managed; do
            sudo cp /etc/chromium/policies/managed/kiosk_child_policy.json "$d/" 2>/dev/null || true
        done

        # 3. Escreve políticas Enterprise para Mozilla Firefox (policies.json)
        sudo mkdir -p /etc/firefox/policies \
                     /usr/lib/firefox/distribution \
                     /usr/lib64/firefox/distribution \
                     /usr/share/firefox/distribution 2>/dev/null || true

        cat << 'EOF' | sudo tee /etc/firefox/policies/policies.json > /dev/null
{{
  "policies": {{
    "DisableDeveloperTools": true,
    "DisableFirefoxAccounts": true,
    "DisablePrivateBrowsing": true,
    "BlockAboutConfig": true,
    "BlockAboutProfiles": true,
    "BlockAboutSupport": true,
    "OfferToSaveLogins": false,
    "PasswordManagerEnabled": false,
    "DNSOverHTTPS": {{
      "Enabled": false,
      "Locked": true
    }},
    "ExtensionSettings": {{
      "*": {{
        "installation_mode": "blocked"
      }}
    }}
  }}
}}
EOF

        for d in /usr/lib/firefox/distribution /usr/lib64/firefox/distribution /usr/share/firefox/distribution; do
            if [ -d "$(dirname "$d")" ]; then
                sudo cp /etc/firefox/policies/policies.json "$d/" 2>/dev/null || true
            fi
        done

        # 4. Bloqueia atalhos de fechamento (Alt+F4) e alternância (Alt+Tab) no gsettings do sistema
        echo "Bloqueando atalhos de teclado do sistema (Alt+F4, Alt+Tab)..."
        gsettings set org.gnome.desktop.wm.keybindings close "[]" 2>/dev/null || true
        gsettings set org.gnome.desktop.wm.keybindings switch-applications "[]" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm close "[]" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm switch-applications "[]" 2>/dev/null || true

        # 5. Criar wrappers de persistência no /usr/local/bin com suporte a atalhos web (.desktop, --app=, etc.)
        echo "Criando wrappers de persistência para atalhos e aberturas manuais..."
        for b in google-chrome google-chrome-stable chromium-browser chromium brave-browser microsoft-edge-stable msedge opera; do
            real_bin=$(which -a "$b" 2>/dev/null | grep -v "/usr/local/bin" | head -n1)
            if [ -n "$real_bin" ] && [ -x "$real_bin" ]; then
                sudo tee "/usr/local/bin/$b" > /dev/null << EOF
#!/bin/bash
TARGET_URL={safe_url}

for arg in "\$@"; do
    clean_arg="\${{arg#--app=}}"

    if [[ "\$clean_arg" == *.desktop ]] && [ -f "\$clean_arg" ]; then
        url_in_file=\$(grep -E '^URL=' "\$clean_arg" 2>/dev/null | cut -d'=' -f2-)
        if [ -z "\$url_in_file" ]; then
            url_in_file=\$(grep -E '^Exec=' "\$clean_arg" 2>/dev/null | sed -E 's/^Exec=[^ ]+ //; s/ %U//; s/ %u//; s/--app=//')
        fi
        if [ -n "\$url_in_file" ]; then
            clean_arg="\$url_in_file"
        fi
    fi

    if [[ "\$clean_arg" == http://* ]] || [[ "\$clean_arg" == https://* ]] || [[ "\$clean_arg" == www.* ]] || [[ "\$clean_arg" == *matific* ]] || [[ "\$clean_arg" == *.com* ]] || [[ "\$clean_arg" == *.br* ]]; then
        if [[ "\$clean_arg" == www.* ]] || [[ "\$clean_arg" == matific.* ]]; then
            TARGET_URL="https://\$clean_arg"
        else
            TARGET_URL="\$clean_arg"
        fi
    elif [[ "\$clean_arg" != %* ]] && [[ "\$clean_arg" != --* ]] && [ -n "\$clean_arg" ]; then
        TARGET_URL="\$clean_arg"
    fi
done

if [[ "\$TARGET_URL" != http://* ]] && [[ "\$TARGET_URL" != https://* ]] && [[ "\$TARGET_URL" != /* ]]; then
    TARGET_URL="https://\$TARGET_URL"
fi

exec "$real_bin" --kiosk --no-sandbox --no-first-run --disable-context-menu --disable-pinch --overscroll-history-navigation=0 --disable-translate --no-default-browser-check "\$TARGET_URL"
EOF
                sudo chmod 755 "/usr/local/bin/$b"
            fi
        done

        firefox_real=$(which -a firefox 2>/dev/null | grep -v "/usr/local/bin" | head -n1)
        if [ -n "$firefox_real" ] && [ -x "$firefox_real" ]; then
            sudo tee "/usr/local/bin/firefox" > /dev/null << EOF
#!/bin/bash
TARGET_URL={safe_url}

for arg in "\$@"; do
    clean_arg="\${{arg#--app=}}"
    if [[ "\$clean_arg" == *.desktop ]] && [ -f "\$clean_arg" ]; then
        url_in_file=\$(grep -E '^URL=' "\$clean_arg" 2>/dev/null | cut -d'=' -f2-)
        [ -n "\$url_in_file" ] && clean_arg="\$url_in_file"
    fi
    if [[ "\$clean_arg" == http://* ]] || [[ "\$clean_arg" == https://* ]] || [[ "\$clean_arg" == www.* ]] || [[ "\$clean_arg" == *matific* ]] || [[ "\$clean_arg" == *.com* ]] || [[ "\$clean_arg" == *.br* ]]; then
        TARGET_URL="\$clean_arg"
    fi
done

if [[ "\$TARGET_URL" != http://* ]] && [[ "\$TARGET_URL" != https://* ]] && [[ "\$TARGET_URL" != /* ]]; then
    TARGET_URL="https://\$TARGET_URL"
fi

exec "$firefox_real" --kiosk "\$TARGET_URL"
EOF
            sudo chmod 755 "/usr/local/bin/firefox"
        fi

        # 6. Encerra instâncias anteriores de qualquer navegador
        pkill -x google-chrome 2>/dev/null || true
        pkill -x chrome 2>/dev/null || true
        pkill -x chromium-browser 2>/dev/null || true
        pkill -x chromium 2>/dev/null || true
        pkill -x brave 2>/dev/null || true
        pkill -x brave-browser 2>/dev/null || true
        pkill -x msedge 2>/dev/null || true
        pkill -x opera 2>/dev/null || true
        pkill -x firefox 2>/dev/null || true
        sleep 1

        # 7. Descobre usuário gráfico ativo e ambiente X11
        LOGGED_USER=$(who | grep -E '(:0|tty|x11)' | awk '{{print $1}}' | head -n1)
        if [ -z "$LOGGED_USER" ]; then
            LOGGED_USER=$(who | awk '{{print $1}}' | head -n1)
        fi
        if [ -z "$LOGGED_USER" ]; then
            LOGGED_USER="aluno"
        fi

        USER_ID=$(id -u "$LOGGED_USER" 2>/dev/null || echo 1000)
        export DISPLAY=${{DISPLAY:-:0}}
        
        XAUTH_CANDIDATE=""
        for f in "/run/user/$USER_ID/gdm/Xauthority" "/run/user/$USER_ID/.mutter-Xwayland-Xauthority" "/home/$LOGGED_USER/.Xauthority"; do
            if [ -f "$f" ]; then
                XAUTH_CANDIDATE="$f"
                break
            fi
        done
        if [ -n "$XAUTH_CANDIDATE" ]; then
            export XAUTHORITY="$XAUTH_CANDIDATE"
        fi

        # 8. Detecta qual navegador está instalado e inicia no modo Kiosk
        LAUNCH_BIN=""
        if command -v google-chrome &> /dev/null; then
            LAUNCH_BIN="google-chrome"
        elif command -v chromium-browser &> /dev/null; then
            LAUNCH_BIN="chromium-browser"
        elif command -v chromium &> /dev/null; then
            LAUNCH_BIN="chromium"
        elif command -v brave-browser &> /dev/null; then
            LAUNCH_BIN="brave-browser"
        elif command -v microsoft-edge-stable &> /dev/null; then
            LAUNCH_BIN="microsoft-edge-stable"
        elif command -v opera &> /dev/null; then
            LAUNCH_BIN="opera"
        elif command -v firefox &> /dev/null; then
            LAUNCH_BIN="firefox"
        fi

        if [ -n "$LAUNCH_BIN" ]; then
            echo "Iniciando $LAUNCH_BIN em Modo Kiosk para {safe_url} (Usuário: $LOGGED_USER)..."
            
            if [ "$LAUNCH_BIN" = "firefox" ]; then
                K_ARGS="--kiosk {safe_url}"
            else
                K_ARGS="--kiosk --no-sandbox --no-first-run --disable-context-menu --disable-pinch --overscroll-history-navigation=0 --disable-translate --no-default-browser-check {safe_url}"
            fi

            if [ "$LOGGED_USER" != "root" ] && id "$LOGGED_USER" &>/dev/null; then
                sudo -u "$LOGGED_USER" DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" nohup $LAUNCH_BIN $K_ARGS </dev/null >/dev/null 2>&1 &
            else
                nohup $LAUNCH_BIN $K_ARGS </dev/null >/dev/null 2>&1 &
            fi
            echo "✅ Modo Kiosk Infantil ativado com sucesso! Futuras aberturas manuais também abrirão em Kiosk."
        else
            echo "❌ Nenhum navegador instalado (Chrome, Chromium, Brave, Edge, Opera ou Firefox) foi encontrado na máquina." >&2
            exit 1
        fi
    """
    return script.strip(), None

@register_command('desativar_modo_kiosk_infantil', 'Desativar Modo Kiosk Infantil', 'Configurações do Navegador', icon='minimize-2', is_streaming=True)
def _build_disable_kiosk_mode(data: Dict[str, Any]) -> Tuple[str, None]:
    """Restaura as políticas padrão do navegador e reativa atalhos do sistema."""
    script = f"""
        {GSETTINGS_ENV_SETUP}

        echo "Removendo wrappers de persistência do /usr/local/bin..."
        sudo rm -f /usr/local/bin/google-chrome \
                   /usr/local/bin/google-chrome-stable \
                   /usr/local/bin/chromium-browser \
                   /usr/local/bin/chromium \
                   /usr/local/bin/brave-browser \
                   /usr/local/bin/microsoft-edge-stable \
                   /usr/local/bin/msedge \
                   /usr/local/bin/opera \
                   /usr/local/bin/firefox

        echo "Removendo políticas de Modo Kiosk Infantil de todos os navegadores..."
        sudo rm -f /etc/chromium/policies/managed/kiosk_child_policy.json
        sudo rm -f /etc/opt/chrome/policies/managed/kiosk_child_policy.json
        sudo rm -f /etc/brave/policies/managed/kiosk_child_policy.json
        sudo rm -f /etc/brave-browser/policies/managed/kiosk_child_policy.json
        sudo rm -f /etc/opt/edge/policies/managed/kiosk_child_policy.json
        sudo rm -f /etc/opera/policies/managed/kiosk_child_policy.json
        sudo rm -f /etc/firefox/policies/policies.json
        sudo rm -f /usr/lib/firefox/distribution/policies.json
        sudo rm -f /usr/lib64/firefox/distribution/policies.json
        sudo rm -f /usr/share/firefox/distribution/policies.json

        echo "Restaurando atalhos de teclado do sistema (Alt+F4, Alt+Tab)..."
        gsettings set org.gnome.desktop.wm.keybindings close "['<Alt>F4']" 2>/dev/null || true
        gsettings set org.gnome.desktop.wm.keybindings switch-applications "['<Alt>Tab']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm close "['<Alt>F4']" 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.wm switch-applications "['<Alt>Tab']" 2>/dev/null || true

        echo "Encerrando navegadores em Modo Kiosk..."
        pkill -x google-chrome 2>/dev/null || true
        pkill -x chrome 2>/dev/null || true
        pkill -x chromium-browser 2>/dev/null || true
        pkill -x chromium 2>/dev/null || true
        pkill -x brave 2>/dev/null || true
        pkill -x brave-browser 2>/dev/null || true
        pkill -x msedge 2>/dev/null || true
        pkill -x opera 2>/dev/null || true
        pkill -x firefox 2>/dev/null || true

        echo "✅ Modo Kiosk Infantil desativado com sucesso. Navegadores restaurados para o modo normal."
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

@register_command('ativar_protecao_tela', 'Ativar Proteção de Tela', 'Controle da Interface', icon='shield')
def _build_enable_screensaver_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Constrói um comando para ativar a proteção de tela e o bloqueio automático por inatividade."""
    script = GSETTINGS_ENV_SETUP + """
        timeout 3 gsettings set org.cinnamon.desktop.screensaver lock-enabled true >/dev/null 2>&1 || true
        timeout 3 gsettings set org.cinnamon.desktop.screensaver idle-activation-enabled true >/dev/null 2>&1 || true
        timeout 3 gsettings set org.cinnamon.desktop.session idle-delay 900 >/dev/null 2>&1 || true
        timeout 3 gsettings set org.gnome.desktop.screensaver lock-enabled true >/dev/null 2>&1 || true
        timeout 3 gsettings set org.gnome.desktop.session idle-delay 900 >/dev/null 2>&1 || true
        timeout 3 gsettings set org.mate.screensaver lock-enabled true >/dev/null 2>&1 || true
        timeout 3 gsettings set org.mate.session idle-delay 900 >/dev/null 2>&1 || true
        timeout 3 xset s on >/dev/null 2>&1 || true
        timeout 3 xset +dpms >/dev/null 2>&1 || true
        timeout 3 cinnamon-screensaver-command -a >/dev/null 2>&1 || timeout 3 xdg-screensaver lock >/dev/null 2>&1 || timeout 3 gnome-screensaver-command -l >/dev/null 2>&1 || timeout 3 xscreensaver-command -lock >/dev/null 2>&1 || timeout 3 xset s activate >/dev/null 2>&1 || true
        echo "Proteção de tela e bloqueio por inatividade foram ativados com sucesso."
    """
    return script, None

@register_command('desativar_protecao_tela', 'Remover Proteção de Tela', 'Controle da Interface', icon='shield-off')
def _build_disable_screensaver_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Constrói um comando para desativar e remover a proteção de tela e o bloqueio por inatividade."""
    script = GSETTINGS_ENV_SETUP + """
        timeout 3 cinnamon-screensaver-command -d >/dev/null 2>&1 || timeout 3 xdg-screensaver deactivate >/dev/null 2>&1 || timeout 3 gnome-screensaver-command -d >/dev/null 2>&1 || timeout 3 xset s reset >/dev/null 2>&1 || true
        timeout 3 gsettings set org.cinnamon.desktop.session idle-delay 0 >/dev/null 2>&1 || true
        timeout 3 gsettings set org.cinnamon.desktop.screensaver lock-enabled false >/dev/null 2>&1 || true
        timeout 3 gsettings set org.cinnamon.desktop.screensaver idle-activation-enabled false >/dev/null 2>&1 || true
        timeout 3 gsettings set org.gnome.desktop.session idle-delay 0 >/dev/null 2>&1 || true
        timeout 3 gsettings set org.gnome.desktop.screensaver lock-enabled false >/dev/null 2>&1 || true
        timeout 3 gsettings set org.mate.session idle-delay 0 >/dev/null 2>&1 || true
        timeout 3 gsettings set org.mate.screensaver lock-enabled false >/dev/null 2>&1 || true
        timeout 3 xset s off >/dev/null 2>&1 || true
        timeout 3 xset -dpms >/dev/null 2>&1 || true
        timeout 3 xset s reset >/dev/null 2>&1 || true
        echo "Proteção de tela e bloqueio por inatividade foram completamente removidos/desativados."
    """
    return script, None

@register_command('configurar_protecao_tela', 'Configurar Proteção de Tela', 'Controle da Interface', icon='sliders')
def _build_config_screensaver_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Constrói um comando para configurar os tempos e comportamento da proteção de tela."""
    idle_delay = int(data.get('idle_delay', 300))
    lock_delay = int(data.get('lock_delay', 0))
    lock_enabled = 'true' if data.get('lock_enabled', True) else 'false'
    idle_activation = 'true' if data.get('idle_activation_enabled', True) else 'false'

    script = GSETTINGS_ENV_SETUP + f"""
        timeout 3 gsettings set org.cinnamon.desktop.session idle-delay {idle_delay} >/dev/null 2>&1 || true
        timeout 3 gsettings set org.cinnamon.desktop.screensaver lock-enabled {lock_enabled} >/dev/null 2>&1 || true
        timeout 3 gsettings set org.cinnamon.desktop.screensaver lock-delay {lock_delay} >/dev/null 2>&1 || true
        timeout 3 gsettings set org.cinnamon.desktop.screensaver idle-activation-enabled {idle_activation} >/dev/null 2>&1 || true
        
        timeout 3 gsettings set org.gnome.desktop.session idle-delay {idle_delay} >/dev/null 2>&1 || true
        timeout 3 gsettings set org.gnome.desktop.screensaver lock-enabled {lock_enabled} >/dev/null 2>&1 || true
        timeout 3 gsettings set org.gnome.desktop.screensaver lock-delay {lock_delay} >/dev/null 2>&1 || true
        
        timeout 3 gsettings set org.mate.session idle-delay {idle_delay} >/dev/null 2>&1 || true
        timeout 3 gsettings set org.mate.screensaver lock-enabled {lock_enabled} >/dev/null 2>&1 || true
        timeout 3 gsettings set org.mate.screensaver lock-delay {lock_delay} >/dev/null 2>&1 || true
        echo "Configurações de proteção de tela aplicadas com sucesso."
    """
    return script, None
register_command('resetar_multiseat', 'Resetar Seats', 'Multiseat', icon='trash', command_or_func=lambda d: ("loginctl flush-devices && echo 'Todas as configurações de dispositivos de seat foram limpas (flush).'", None))
register_command('status_multiseat', 'Status do Seat1', 'Multiseat', icon='activity', command_or_func=lambda d: ("loginctl seat-status seat1 || echo 'Seat1 não está ativo ou não encontrado.'", None))

# --- Comandos que requerem scripts mais complexos ---

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


@register_command('monitorar_rede', 'Monitorar Tráfego de Rede', 'Monitoramento', icon='activity', is_streaming=True)
def _build_monitor_network_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Monitora o tráfego de rede (KB/s) em tempo real usando ifstat."""
    return """
        IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
        if [ -z "$IFACE" ]; then echo "Erro: Interface de rede não detectada." >&2; exit 1; fi
        
        if ! command -v ifstat &> /dev/null; then
            echo "Instalando ifstat no dispositivo remoto..."
            sudo apt-get update -qq && sudo apt-get install -y ifstat > /dev/null 2>&1
        fi
        
        echo "Monitorando interface $IFACE (15 segundos)..."
        ifstat -i "$IFACE" 1 15
    """, None

@register_command('definir_limite_banda', 'Limitar Banda de Internet', 'Gerenciamento do Sistema', icon='activity', require_field='bandwidth-group')
def _build_set_bandwidth_limit(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Aplica limites de Download e Upload usando tc (Traffic Control)."""
    download = data.get('download_limit', '2000') # kbps
    upload = data.get('upload_limit', '1000')     # kbps
    
    script = f"""
        # Detecta interface padrão
        IFACE=$(ip route | grep default | awk '{{print $5}}' | head -n1)
        if [ -z "$IFACE" ]; then echo "Erro: Interface de rede não detectada." >&2; exit 1; fi

        echo "Limpando configurações anteriores na interface $IFACE..."
        sudo tc qdisc del dev $IFACE root 2>/dev/null || true
        sudo tc qdisc del dev $IFACE ingress 2>/dev/null || true

        echo "Aplicando limites na interface $IFACE..."
        
        # Limite de Upload (Egress) usando HTB
        sudo tc qdisc add dev $IFACE root handle 1: htb default 10
        sudo tc class add dev $IFACE parent 1: classid 1:10 htb rate {upload}kbit ceil {upload}kbit

        # Limite de Download (Ingress) usando Ingress Policer
        sudo tc qdisc add dev $IFACE handle ffff: ingress
        # Aplica o limite para IPv4 e IPv6 usando seletores universais (match u32 0 0)
        sudo tc filter add dev $IFACE parent ffff: protocol ip prio 50 u32 match u32 0 0 police rate {download}kbit burst 32k drop
        sudo tc filter add dev $IFACE parent ffff: protocol ipv6 prio 51 u32 match u32 0 0 police rate {download}kbit burst 32k drop

        echo "Sucesso: Download limitado a {download}kbps e Upload a {upload}kbps."
    """
    return script.strip(), None

@register_command('remover_limite_banda', 'Remover Limite de Banda', 'Gerenciamento do Sistema', icon='zap-off')
def _build_remove_bandwidth_limit(data: Dict[str, Any]) -> Tuple[str, None]:
    """Remove todas as restrições de tráfego aplicadas via tc."""
    return """
        IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
        if [ -n "$IFACE" ]; then
            sudo tc qdisc del dev $IFACE root 2>/dev/null || true
            sudo tc qdisc del dev $IFACE ingress 2>/dev/null || true
            echo "Todos os limites de banda foram removidos da interface $IFACE."
        fi
    """, None

@register_command('testar_velocidade', 'Testar Velocidade da Internet', 'Monitoramento', icon='zap', is_streaming=True)
def _build_speedtest_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Executa o speedtest-cli para testar a velocidade da internet.
    Instala a ferramenta se não estiver presente.
    """
    return """
        if ! command -v speedtest &> /dev/null; then
            echo "Instalando speedtest-cli no dispositivo remoto..."
            # Tenta instalar via pip (mais comum para speedtest-cli)
            sudo apt-get update -qq && sudo apt-get install -y python3-pip > /dev/null 2>&1
            sudo pip3 install speedtest-cli > /dev/null 2>&1
            if ! command -v speedtest &> /dev/null; then
                echo "Erro: Falha ao instalar speedtest-cli. Tentando via apt..." >&2
                sudo apt-get update -qq && sudo apt-get install -y speedtest-cli > /dev/null 2>&1
            fi
        fi
        echo "Iniciando teste de velocidade (pode demorar alguns segundos)..."
        speedtest --simple --share
    """, None

# --- Gerenciamento de Energia para Linux Mint 22.1 Cinnamon ---

@register_command('configurar_energia_cinnamon', 'Configurar Opções de Energia Cinnamon', 'Gerenciamento de Energia', icon='zap', no_sudo=True)
def _build_configurar_energia_cinnamon(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Aplica configurações de inatividade, suspensão, monitor e ações de botões no Linux Mint Cinnamon via gsettings.
    """
    disp_sleep_sec = int(data.get('display_sleep', 0)) * 60
    suspend_sec = int(data.get('suspend_timeout', 0)) * 60
    idle_delay_sec = int(data.get('idle_delay', 0)) * 60
    
    pwr_btn = shlex.quote(str(data.get('power_button_action', 'interactive')))
    lid_close = shlex.quote(str(data.get('lid_close_action', 'suspend')))
    
    lock_suspend = 'true' if data.get('lock_on_suspend', True) else 'false'
    lock_enabled = 'true' if data.get('lock_enabled', True) else 'false'
    
    suspend_type = 'suspend' if suspend_sec > 0 else 'nothing'

    cmd = GSETTINGS_ENV_SETUP + f"""
        # 1. Gravação direta de alta performance via dconf (sem bloqueio no bus DBus)
        dconf write /org/cinnamon/settings-daemon/plugins/power/sleep-display-ac {disp_sleep_sec} >/dev/null 2>&1 || true
        dconf write /org/cinnamon/desktop/session/idle-delay {idle_delay_sec} >/dev/null 2>&1 || true
        dconf write /org/cinnamon/settings-daemon/plugins/power/sleep-inactive-ac-timeout {suspend_sec} >/dev/null 2>&1 || true
        dconf write /org/cinnamon/settings-daemon/plugins/power/sleep-inactive-ac-type "'{suspend_type}'" >/dev/null 2>&1 || true
        dconf write /org/cinnamon/settings-daemon/plugins/power/button-power "'{pwr_btn}'" >/dev/null 2>&1 || true
        dconf write /org/cinnamon/settings-daemon/plugins/power/lid-close-ac "'{lid_close}'" >/dev/null 2>&1 || true
        dconf write /org/cinnamon/settings-daemon/plugins/power/lock-on-suspend {lock_suspend} >/dev/null 2>&1 || true
        dconf write /org/cinnamon/desktop/screensaver/lock-enabled {lock_enabled} >/dev/null 2>&1 || true

        # 2. Notificação gsettings resiliente com timeout máximo de 2s
        timeout 2 gsettings set org.cinnamon.settings-daemon.plugins.power sleep-display-ac {disp_sleep_sec} >/dev/null 2>&1 || true
        timeout 2 gsettings set org.cinnamon.desktop.session idle-delay {idle_delay_sec} >/dev/null 2>&1 || true
        timeout 2 gsettings set org.cinnamon.settings-daemon.plugins.power sleep-inactive-ac-timeout {suspend_sec} >/dev/null 2>&1 || true
        timeout 2 gsettings set org.cinnamon.settings-daemon.plugins.power sleep-inactive-ac-type '{suspend_type}' >/dev/null 2>&1 || true
        timeout 2 gsettings set org.cinnamon.settings-daemon.plugins.power button-power '{pwr_btn}' >/dev/null 2>&1 || true
        timeout 2 gsettings set org.cinnamon.settings-daemon.plugins.power lid-close-ac '{lid_close}' >/dev/null 2>&1 || true
        timeout 2 gsettings set org.cinnamon.settings-daemon.plugins.power lock-on-suspend {lock_suspend} >/dev/null 2>&1 || true
        timeout 2 gsettings set org.cinnamon.desktop.screensaver lock-enabled {lock_enabled} >/dev/null 2>&1 || true

        echo "Opções de energia Cinnamon atualizadas com sucesso."
    """
    return cmd, None

@register_command('desligar_maquinas', 'Desligar Computador Impossibilitando Acesso', 'Gerenciamento de Energia', icon='power', is_dangerous=True)
def _build_desligar_maquinas(data: Dict[str, Any]) -> Tuple[str, None]:
    return "sudo shutdown -h now 2>/dev/null || sudo systemctl poweroff", None

@register_command('reiniciar_maquinas', 'Reiniciar Computador', 'Gerenciamento de Energia', icon='refresh-cw', is_dangerous=True)
def _build_reiniciar_maquinas(data: Dict[str, Any]) -> Tuple[str, None]:
    return "sudo shutdown -r now 2>/dev/null || sudo systemctl reboot", None

@register_command('suspender_maquinas', 'Suspender Computador (Sleep)', 'Gerenciamento de Energia', icon='moon')
def _build_suspender_maquinas(data: Dict[str, Any]) -> Tuple[str, None]:
    return "sudo systemctl suspend 2>/dev/null || echo 'Falha ao suspender'", None

@register_command('bloquear_tela_cinnamon', 'Bloquear Sessão de Usuário', 'Gerenciamento de Energia', icon='lock')
def _build_bloquear_tela_cinnamon(data: Dict[str, Any]) -> Tuple[str, None]:
    return GSETTINGS_ENV_SETUP + "timeout 3 cinnamon-screensaver-command -l 2>/dev/null || timeout 3 xdg-screensaver lock 2>/dev/null || true", None

@register_command('logout_cinnamon', 'Encerrar Sessão (Logoff)', 'Gerenciamento de Energia', icon='log-out')
def _build_logout_cinnamon(data: Dict[str, Any]) -> Tuple[str, None]:
    return GSETTINGS_ENV_SETUP + "timeout 3 cinnamon-session-quit --logout --no-prompt 2>/dev/null || pkill -KILL -u $USER 2>/dev/null || true", None

@register_command('agendar_desligamento', 'Agendar Desligamento do Sistema', 'Gerenciamento de Energia', icon='clock')
def _build_agendar_desligamento(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    minutes = int(data.get('minutes', 15))
    msg = data.get('message', 'O computador será desligado em instantes pelo administrador.')
    safe_msg = shlex.quote(msg)
    return f"sudo shutdown -h +{minutes} {safe_msg}", None

@register_command('cancelar_desligamento_agendado', 'Cancelar Desligamento Agendado', 'Gerenciamento de Energia', icon='x-octagon')
def _build_cancelar_desligamento_agendado(data: Dict[str, Any]) -> Tuple[str, None]:
    return "sudo shutdown -c 2>/dev/null && echo 'Desligamento agendado cancelado com sucesso.'", None

@register_command('habilitar_wol_cliente', 'Habilitar Wake-on-LAN no Linux (ethtool & NetworkManager)', 'Gerenciamento de Energia', icon='zap')
def _build_habilitar_wol_cliente(data: Dict[str, Any]) -> Tuple[str, None]:
    cmd = """
        which ethtool >/dev/null 2>&1 || (sudo apt-get update -qq && sudo apt-get install -y -qq ethtool)
        IFACE=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++)if($i=="dev")print $(i+1)}')
        if [ -n "$IFACE" ]; then
            sudo ethtool -s "$IFACE" wol g 2>/dev/null || true
            echo "Ethtool WoL ativado na interface $IFACE."
        fi
        if which nmcli >/dev/null 2>&1; then
            for conn in $(nmcli -t -f UUID connection show 2>/dev/null); do
                nmcli connection modify "$conn" 802-3-ethernet.wake-on-lan magic 2>/dev/null || true
            done
            echo "NetworkManager configurado para WoL magic packet."
        fi
        cat << 'EOF' | sudo tee /etc/systemd/system/wol-enable.service >/dev/null
[Unit]
Description=Enable Wake-on-LAN on Network Interfaces
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'for dev in $(ls /sys/class/net/); do [ "$dev" != "lo" ] && ethtool -s "$dev" wol g 2>/dev/null || true; done'

[Install]
WantedBy=basic.target
EOF
        sudo systemctl daemon-reload >/dev/null 2>&1 || true
        sudo systemctl enable wol-enable.service >/dev/null 2>&1 || true
        echo "Serviço de persistência WoL instalado com sucesso no cliente."
    """
    return cmd, None

