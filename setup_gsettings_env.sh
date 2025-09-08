#!/bin/bash
# setup_gsettings_env.sh
# Este script configura o ambiente necessário para que os comandos 'gsettings'
# possam ser executados corretamente em uma sessão SSH.

# Ativa o modo de depuração (trace) se a variável de ambiente DEBUG_MODE estiver definida como "true".
# Isso imprime cada comando antes de executá-lo, ajudando a diagnosticar problemas.
if [[ "${DEBUG_MODE}" == "true" ]]; then set -x; fi

# Garante que temos um ID de usuário para trabalhar.
USER_ID=$(id -u)
if [ -z "$USER_ID" ]; then
    echo "Erro: Não foi possível obter o ID do usuário." >&2
    exit 1
fi

# Define a variável DISPLAY, que é necessária para muitos comandos de desktop.
export DISPLAY=:0

# Tenta encontrar o PID de uma sessão de desktop ativa para o usuário atual.
# A busca é feita por nomes de processo comuns de diferentes ambientes de desktop.
# -f: Corresponde à linha de comando completa.
# -o: Seleciona apenas o processo mais antigo (geralmente a sessão principal).
SESSION_NAMES="gnome-session|cinnamon-session|mate-session|xfce4-session|plasma"
PID=$(pgrep -f -o -u "$USER_ID" "$SESSION_NAMES")

# Inicializa a variável de endereço.
DBUS_SESSION_BUS_ADDRESS=""

# Se um PID foi encontrado, tenta extrair o endereço do D-Bus do ambiente do processo.
if [ -n "$PID" ]; then
    # Extrai o endereço do D-Bus do ambiente do processo.
    # O arquivo /proc/$PID/environ usa bytes nulos como separadores.
    # Este comando awk encontra a linha que começa com "DBUS_SESSION_BUS_ADDRESS="
    # e remove esse prefixo, imprimindo o resto da linha (o valor real).
    # Isso lida corretamente com valores que contêm '='.
    DBUS_SESSION_BUS_ADDRESS=$(awk -v RS='\0' '/^DBUS_SESSION_BUS_ADDRESS=/ { sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }' "/proc/$PID/environ")
fi

# CONDIÇÃO DE FALLBACK: Se, após a tentativa acima, a variável AINDA estiver vazia,
# usamos o caminho de socket padrão, que é um método de fallback muito confiável.
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus"
fi

# Exporta a variável final para que os comandos subsequentes (gsettings, etc.) possam usá-la.
export DBUS_SESSION_BUS_ADDRESS

# O comando que é anexado a este script pelo app.py será executado a seguir,
# herdando as variáveis de ambiente exportadas.