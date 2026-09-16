#!/bin/bash
#
# Script para ativar ou desativar todos os dispositivos de entrada (mouse, teclado, touchpad).
# Recebe a ação ('enable' or 'disable') como primeiro argumento.
# Este script deve ser executado no contexto do usuário com sessão gráfica.

set -euo pipefail # Sair em caso de erro

ACTION="${1:-}"

if [[ "$ACTION" != "enable" ]] && [[ "$ACTION" != "disable" ]]; then
    echo "Erro: Ação inválida. Use 'enable' ou 'disable'." >&2
    exit 1
fi

# O comando 'xinput' precisa do ambiente gráfico.
# O script Python que chama este deve garantir que DISPLAY e XAUTHORITY estão definidos.
if ! command -v xinput &> /dev/null; then
    echo "Erro: O comando 'xinput' não foi encontrado na máquina remota." >&2
    exit 1
fi

SUCCESS_COUNT=0
if [[ "$ACTION" == "enable" ]]; then
    # 1. Acorda os dispositivos USB HID e desativa economia/autosuspend no kernel
    if [ -d /sys/bus/usb/devices ]; then
        for f in /sys/bus/usb/devices/*/power/control; do [ -w "$f" ] && echo on > "$f" 2>/dev/null || true; done
        for f in /sys/bus/usb/devices/*/power/autosuspend; do [ -w "$f" ] && echo -1 > "$f" 2>/dev/null || true; done
    fi
    udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true
    udevadm trigger --subsystem-match=hid --action=change 2>/dev/null || true

    # 2. Identifica os Master Keyboards e Master Pointers no X11
    MASTER_KBD=$(xinput list 2>/dev/null | awk '/Virtual core keyboard|master keyboard/ {for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {split($i,a,"="); print a[2]}}' | head -n 1)
    [ -z "$MASTER_KBD" ] && MASTER_KBD=3

    MASTER_PTR=$(xinput list 2>/dev/null | awk '/Virtual core pointer|master pointer/ {for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {split($i,a,"="); print a[2]}}' | head -n 1)
    [ -z "$MASTER_PTR" ] && MASTER_PTR=2

    MASTER_IDS=$(xinput list 2>/dev/null | awk '/master/ { for (i=1; i<=NF; i++) if ($i ~ /^id=[0-9]+$/) { split($i, a, "="); print a[2]; } }')
    for m_id in $MASTER_IDS; do
        xinput enable "$m_id" 2>/dev/null || true
        xinput set-prop "$m_id" "Device Enabled" 1 2>/dev/null || true
    done

    # 3. Itera por todos os dispositivos, reativa e REANEXA slaves flutuantes aos masters
    ALL_IDS=$(xinput list --id-only 2>/dev/null || true)
    for id in $ALL_IDS; do
        DEV_NAME=$(xinput list --name-only "$id" 2>/dev/null || true)
        if echo "$DEV_NAME" | grep -qi "XTEST"; then
            continue
        fi
        if echo " $MASTER_IDS " | grep -q " $id "; then
            continue
        fi

        xinput enable "$id" 2>/dev/null && SUCCESS_COUNT=$((SUCCESS_COUNT+1))
        xinput set-prop "$id" "Device Enabled" 1 2>/dev/null || true

        DEV_INFO=$(xinput list "$id" 2>/dev/null || true)
        # Teclados (inclui sub-interfaces HID de teclados multimídia/gamer/usb genéricos)
        if echo "$DEV_INFO" | grep -qi "KeyClass" || echo "$DEV_NAME" | grep -qi -E "keyboard|key|kbd"; then
            xinput reattach "$id" "$MASTER_KBD" 2>/dev/null || true
        fi
        # Mouses e Ponteiros
        if echo "$DEV_INFO" | grep -qi -E "ButtonClass|ValuatorClass" || echo "$DEV_NAME" | grep -qi -E "mouse|pointer|touchpad|trackpoint|touchscreen"; then
            xinput reattach "$id" "$MASTER_PTR" 2>/dev/null || true
        fi
    done
    setxkbmap br 2>/dev/null || setxkbmap us 2>/dev/null || true
else
    DEVICE_IDS=$(xinput list 2>/dev/null | awk '
        /slave/ && (tolower($0) ~ /keyboard|mouse|touchpad|pointer|trackpoint|touchscreen/) && !(tolower($0) ~ /xtest/) {
            for (i=1; i<=NF; i++) {
                if ($i ~ /^id=[0-9]+$/) {
                    split($i, a, "=");
                    print a[2];
                }
            }
        }
    ')
    for id in $DEVICE_IDS; do
        xinput disable "$id" 2>/dev/null && SUCCESS_COUNT=$((SUCCESS_COUNT+1))
        xinput set-prop "$id" "Device Enabled" 0 2>/dev/null || true
    done
fi

MESSAGE_ACTION=$([[ "$ACTION" == "enable" ]] && echo "ativados" || echo "desativados")
echo "Ação concluída. ${SUCCESS_COUNT} dispositivo(s) foram ${MESSAGE_ACTION}."