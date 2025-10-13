#!/bin/bash
# setup_x11_env.sh
# Este script configura um ambiente X11 robusto para comandos como 'xinput' e 'zenity'
# serem executados corretamente em uma sessão SSH.

# --- Robust X11 environment setup ---
# Quando executado com 'sudo -u <username>', 'whoami' retorna '<username>'
CURRENT_USER=$(whoami)
USER_ID=$(id -u "$CURRENT_USER")
XAUTH_FILE=""
DISPLAY_VAR=""
XDG_RUNTIME_DIR_FROM_PROC="" # Variável temporária para XDG_RUNTIME_DIR do ambiente do processo

# Encontra PIDs de servidores X ou processos de sessão relevantes
# Prioriza Xorg/Xwayland como fontes diretas do display, depois gerenciadores de sessão
PIDS=$(pgrep -f -u "$USER_ID" "Xorg|Xwayland|gnome-shell|cinnamon|mate-session|xfce4-session|plasma|gnome-session|cinnamon-session")

for PID in $PIDS; do # A palavra-chave 'do' estava faltando aqui.
    # Extrai variáveis de ambiente do /proc/$PID/environ
    # 'strings' é usado para converter os pares KEY=VALUE separados por nulos em linhas separadas,
    # e 'grep' filtra as variáveis de interesse.
    ENV_OUTPUT=$(strings /proc/$PID/environ 2>/dev/null | grep -E '^(DISPLAY|XAUTHORITY|XDG_RUNTIME_DIR)=')
    
    if [ -n "$ENV_OUTPUT" ]; then
        CURRENT_DISPLAY=""
        CURRENT_XAUTHORITY=""
        CURRENT_XDG_RUNTIME_DIR=""
        # Analisa a saída linha por linha
        while IFS='=' read -r key value; do # A palavra-chave 'do' estava faltando aqui.
            case "$key" in
                DISPLAY) CURRENT_DISPLAY="$value" ;;
                XAUTHORITY) CURRENT_XAUTHORITY="$value" ;;
                XDG_RUNTIME_DIR) CURRENT_XDG_RUNTIME_DIR="$value" ;;
            esac
        done <<< "$ENV_OUTPUT"

        # Se encontramos DISPLAY e XAUTHORITY, e o arquivo XAUTHORITY existe, podemos parar
        if [ -n "$CURRENT_DISPLAY" ] && [ -n "$CURRENT_XAUTHORITY" ] && [ -f "$CURRENT_XAUTHORITY" ]; then
            DISPLAY_VAR="$CURRENT_DISPLAY"
            XAUTH_FILE="$CURRENT_XAUTHORITY"
            XDG_RUNTIME_DIR_FROM_PROC="$CURRENT_XDG_RUNTIME_DIR"
            break # Encontrou um ambiente adequado, sai do loop
        fi
    fi # Fecha o if [ -n "$ENV_OUTPUT" ]
done # Fecha o for PID in $PIDS

# Exporta DISPLAY, usando ':0' como padrão se não for encontrado
export DISPLAY=${DISPLAY_VAR:-:0}

# Exporta XDG_RUNTIME_DIR se encontrado do ambiente do processo
if [ -n "$XDG_RUNTIME_DIR_FROM_PROC" ]; then
    export XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR_FROM_PROC"
fi

# Fallback para XAUTHORITY se não foi encontrado ou se o arquivo não existe
if [ -z "$XAUTHORITY" ] || [ ! -f "$XAUTHORITY" ]; then
    # Tenta XDG_RUNTIME_DIR primeiro (se estiver definido e o arquivo existir)
    if [ -n "$XDG_RUNTIME_DIR" ] && [ -f "$XDG_RUNTIME_DIR/.Xauthority" ]; then
        export XAUTHORITY="$XDG_RUNTIME_DIR/.Xauthority"
    # Fallback para o diretório home
    elif [ -f "$HOME/.Xauthority" ]; then
        export XAUTHORITY="$HOME/.Xauthority"
    fi
else
    export XAUTHORITY="$XAUTH_FILE" # Usa o XAUTHORITY encontrado do processo
fi

# Verificação final e aviso se XAUTHORITY ainda não foi encontrado
if [ -z "$XAUTHORITY" ] || [ ! -f "$XAUTHORITY" ]; then
    echo "W: Não foi possível encontrar o arquivo de autorização X11. A ação pode falhar." >&2
fi

# O comando que é anexado a este script pelo app.py será executado a seguir,
# herdando as variáveis de ambiente exportadas.