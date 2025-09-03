#!/bin/bash
# setup_gsettings_env.sh
# Este script configura o ambiente necessário para que os comandos 'gsettings'
# possam ser executados corretamente em uma sessão SSH.

# Encontra o endereço do barramento de sessão D-Bus para o usuário logado
# que está executando a sessão do Cinnamon. Isso é essencial para que o gsettings
# se comunique com os serviços do desktop.
PID=$(pgrep -u "$LOGNAME" cinnamon-session)
if [ -n "$PID" ]; then
    export DBUS_SESSION_BUS_ADDRESS=$(grep -z DBUS_SESSION_BUS_ADDRESS /proc/$PID/environ | cut -d= -f2-)
fi

# Se a variável ainda estiver vazia, tenta um método alternativo para outros ambientes.
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
fi

# O comando que é anexado a este script pelo app.py será executado a seguir,
# herdando as variáveis de ambiente exportadas.