#!/bin/bash
# setup_gsettings_env.sh - Autônomo e compatível com Multiseat
if [[ "${DEBUG_MODE}" == "true" ]]; then set -x; fi

CURRENT_USER=$(whoami)
USER_ID=$(id -u "$CURRENT_USER" 2>/dev/null)

if [ -n "$USER_ID" ]; then
    SESSION_NAMES="gnome-session|cinnamon-session|mate-session|xfce4-session|plasma|Xorg|Xwayland|mutter|kwin|lightdm"
    PID=$(pgrep -f -o -u "$USER_ID" "$SESSION_NAMES" 2>/dev/null)

    if [ -n "$PID" ]; then
        DBUS_ENV=$(awk -v RS='\0' '/^DBUS_SESSION_BUS_ADDRESS=/ { sub(/^DBUS_SESSION_BUS_ADDRESS=/, ""); print }' "/proc/$PID/environ" 2>/dev/null)
        DISP_ENV=$(awk -v RS='\0' '/^DISPLAY=/ { sub(/^DISPLAY=/, ""); print }' "/proc/$PID/environ" 2>/dev/null)
        XAUTH_ENV=$(awk -v RS='\0' '/^XAUTHORITY=/ { sub(/^XAUTHORITY=/, ""); print }' "/proc/$PID/environ" 2>/dev/null)

        if [ -n "$DBUS_ENV" ]; then export DBUS_SESSION_BUS_ADDRESS="$DBUS_ENV"; fi
        if [ -n "$DISP_ENV" ]; then export DISPLAY="$DISP_ENV"; fi
        if [ -n "$XAUTH_ENV" ]; then export XAUTHORITY="$XAUTH_ENV"; fi
    fi

    # Fallback para DBUS
    if [ -z "${DBUS_SESSION_BUS_ADDRESS-}" ]; then
        MODERN_PATH="/run/user/$USER_ID/bus"
        if [ -S "$MODERN_PATH" ]; then
            export DBUS_SESSION_BUS_ADDRESS="unix:path=$MODERN_PATH"
        else
            DBUS_FALLBACK=$(find /tmp -maxdepth 2 -type s -name "bus*" -user "$CURRENT_USER" 2>/dev/null | head -n 1)
            if [ -n "$DBUS_FALLBACK" ]; then export DBUS_SESSION_BUS_ADDRESS="unix:path=$DBUS_FALLBACK"; fi
        fi
    fi

    # Fallback para DISPLAY em multiseat
    if [ -z "${DISPLAY-}" ]; then
        USER_DISP=$(ps -u "$CURRENT_USER" -o args 2>/dev/null | grep -oP ':[0-9]+' | head -n 1)
        if [ -n "$USER_DISP" ]; then
            export DISPLAY="$USER_DISP"
        else
            export DISPLAY=:0
        fi
    fi

    # Fallback para XAUTHORITY em multiseat
    if [ -z "${XAUTHORITY-}" ] || [ ! -f "${XAUTHORITY}" ]; then
        for candidate in "/run/user/$USER_ID/.mutter-Xwayland-Xauthority" "/run/user/$USER_ID/gdm/Xauthority" "/run/user/$USER_ID/.Xauthority" "/var/run/lightdm/root/$DISPLAY" "/run/lightdm/root/$DISPLAY" "$HOME/.Xauthority"; do
            if [ -f "$candidate" ]; then
                export XAUTHORITY="$candidate"
                break
            fi
        done
        if [ -z "${XAUTHORITY-}" ]; then
            XAUTH_FALLBACK=$(ls /run/user/$USER_ID/xauth_* 2>/dev/null | head -n 1)
            if [ -n "$XAUTH_FALLBACK" ]; then export XAUTHORITY="$XAUTH_FALLBACK"; fi
        fi
    fi
fi