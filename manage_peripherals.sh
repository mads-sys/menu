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
    MASTER_IDS=$(xinput list 2>/dev/null | awk '/master/ { for (i=1; i<=NF; i++) if ($i ~ /^id=[0-9]+$/) { split($i, a, "="); print a[2]; } }')
    for m_id in $MASTER_IDS; do
        xinput enable "$m_id" 2>/dev/null || true
    done

    DEVICE_IDS=$(xinput list 2>/dev/null | awk '
        /slave/ && (tolower($0) ~ /keyboard|mouse|touchpad|pointer|trackpoint|touchscreen/) {
            for (i=1; i<=NF; i++) {
                if ($i ~ /^id=[0-9]+$/) {
                    split($i, a, "=");
                    print a[2];
                }
            }
        }
    ')
    for id in $DEVICE_IDS; do
        xinput enable "$id" 2>/dev/null && SUCCESS_COUNT=$((SUCCESS_COUNT+1))
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
    done
fi

MESSAGE_ACTION=$([[ "$ACTION" == "enable" ]] && echo "ativados" || echo "desativados")
echo "Ação concluída. ${SUCCESS_COUNT} dispositivo(s) foram ${MESSAGE_ACTION}."