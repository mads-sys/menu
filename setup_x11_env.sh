#!/bin/bash
# setup_x11_env.sh
# Este script configura um ambiente X11 robusto para comandos como 'xinput' e 'zenity'
# serem executados corretamente em uma sessão SSH, reutilizando a lógica de 'setup_gsettings_env.sh'.

# --- Passo 1: Reutilizar a lógica de detecção de sessão ---
# O 'source' executa o script no contexto atual, permitindo-nos usar as variáveis que ele exporta (como SESSION_PID).
# Encontra o caminho do script gsettings relativo a este script.
GSETTINGS_SCRIPT_PATH="$(dirname "$0")/setup_gsettings_env.sh"
if [ -f "$GSETTINGS_SCRIPT_PATH" ]; then
    source "$GSETTINGS_SCRIPT_PATH"
else
    echo "W: O script 'setup_gsettings_env.sh' não foi encontrado. A detecção do ambiente X11 pode falhar." >&2
fi

# --- Passo 2: Configurar DISPLAY e XAUTHORITY ---
# Tenta extrair as variáveis do ambiente do processo de sessão encontrado.
if [ -n "${SESSION_PID-}" ]; then
    ENV_OUTPUT=$(strings /proc/$SESSION_PID/environ 2>/dev/null | grep -E '^(DISPLAY|XAUTHORITY)=')
    
    # Analisa a saída para definir as variáveis.
    while IFS='=' read -r key value; do
        case "$key" in
            DISPLAY) export DISPLAY="$value" ;;
            XAUTHORITY) export XAUTHORITY="$value" ;;
        esac
    done <<< "$ENV_OUTPUT"
fi

# --- Passo 3: Fallbacks ---
# Se as variáveis não foram encontradas, usa padrões comuns.
if [ -z "${DISPLAY-}" ]; then
    export DISPLAY=:0
fi

if [ -z "${XAUTHORITY-}" ] || [ ! -f "${XAUTHORITY}" ]; then
    # O fallback mais comum e confiável é o arquivo no diretório home do usuário.
    if [ -f "$HOME/.Xauthority" ]; then
        export XAUTHORITY="$HOME/.Xauthority"
    else
        echo "W: Não foi possível encontrar o arquivo de autorização X11. Ações gráficas podem falhar." >&2
    fi
fi

# O comando que é anexado a este script pelo app.py será executado a seguir,
# herdando as variáveis de ambiente exportadas.