#!/bin/bash
# setup_gsettings_env.sh
# Este script configura o ambiente necessário para que os comandos 'gsettings'
# possam ser executados corretamente em uma sessão SSH.

# Ativa o modo de depuração (trace) se a variável de ambiente DEBUG_MODE estiver definida como "true".
# Isso imprime cada comando antes de executá-lo, ajudando a diagnosticar problemas.
if [[ "${DEBUG_MODE}" == "true" ]]; then set -x; fi

# Define a variável DISPLAY, que é necessária para muitos comandos de desktop.
export DISPLAY=:0

# Tenta encontrar o PID de uma sessão de desktop ativa para o usuário atual.
# A busca é feita por nomes de processo comuns. A opção -f é crucial para corresponder à linha de comando completa.
# A opção -o seleciona apenas o processo mais antigo, que geralmente é a sessão principal.
PID=$(pgrep -f -o -u "$(id -u)" "gnome-session|cinnamon-session|mate-session")

# Inicializa a variável de endereço.
DBUS_SESSION_BUS_ADDRESS=""

# Se um PID foi encontrado, tenta extrair o endereço do D-Bus do ambiente do processo.
if [ -n "$PID" ]; then
    # Usa awk para extrair o valor de forma segura, evitando problemas com bytes nulos.
    # -v RS='\0' trata os registros como separados por nulos.
    # -F= trata os campos como separados por '='.
    DBUS_SESSION_BUS_ADDRESS=$(awk -v RS='\0' -F= '$1=="DBUS_SESSION_BUS_ADDRESS" {print $2}' "/proc/$PID/environ")
fi

# CONDIÇÃO DE FALLBACK: Se, após a tentativa acima, a variável AINDA estiver vazia,
# usamos o caminho de socket padrão, que é um método de fallback muito confiável.
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
fi

# Exporta a variável final para que os comandos subsequentes (gsettings, etc.) possam usá-la.
export DBUS_SESSION_BUS_ADDRESS

# O comando que é anexado a este script pelo app.py será executado a seguir,
# herdando as variáveis de ambiente exportadas.