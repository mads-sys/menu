#!/bin/bash
# --- BEGIN GSETTINGS ENVIRONMENT SETUP ---
# Este script configura as variáveis de ambiente necessárias para que o `gsettings`
# possa se comunicar com a sessão D-Bus do usuário logado.

# Garante que o script pare em caso de erro.
set -e

USER_ID=$(id -u)
if [ -z "$USER_ID" ]; then echo "FATAL: Não foi possível obter o USER_ID."; exit 1; fi

export XDG_RUNTIME_DIR="/run/user/$USER_ID"
if [ ! -d "$XDG_RUNTIME_DIR" ]; then echo "FATAL: Diretório XDG_RUNTIME_DIR não encontrado em $XDG_RUNTIME_DIR."; exit 1; fi

# Tentativa 1: Usar o caminho padrão do socket D-Bus, que é o método mais comum.
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

# Se o socket não existir no caminho padrão, tenta encontrá-lo no ambiente do processo da sessão.
if [ ! -S "$XDG_RUNTIME_DIR/bus" ]; then
    # Procura por um processo de sessão gráfica comum (cinnamon, gnome, etc.)
    SESSION_PID=$(pgrep -f -u "$USER_ID" -n "(cinnamon-session|gnome-session|plasma_session)")
    if [ -n "$SESSION_PID" ]; then
        DBUS_ADDRESS_FROM_PROC=$(grep -z DBUS_SESSION_BUS_ADDRESS /proc/$SESSION_PID/environ | cut -d= -f2- | tr -d '\0')
        if [ -n "$DBUS_ADDRESS_FROM_PROC" ]; then
            export DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDRESS_FROM_PROC"
        else
            echo "FATAL: Sessão gráfica encontrada (PID: $SESSION_PID), mas a variável DBUS_SESSION_BUS_ADDRESS não foi encontrada em seu ambiente.";
            exit 1;
        fi
    else
        echo "FATAL: Não foi possível encontrar o socket D-Bus em '$XDG_RUNTIME_DIR/bus' nem encontrar um processo de sessão gráfica ativo.";
        exit 1;
    fi
fi

# Teste final de comunicação para garantir que o gsettings pode se conectar.
gsettings get org.cinnamon.desktop.interface clock-show-date > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "FATAL: A comunicação com o D-Bus falhou. Verifique as permissões ou se a sessão gráfica está corrompida. DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS";
    exit 1;
fi
# --- END GSETTINGS ENVIRONMENT SETUP ---
