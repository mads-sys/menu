#!/bin/bash
#
# Script para ativar ou desativar o clique direito do mouse (botão 3).
# Recebe a ação ('enable' or 'disable') como primeiro argumento.
# Este script deve ser executado no contexto do usuário com sessão gráfica.

set -euo pipefail # Sair em caso de erro

ACTION="${1:-}"
TARGET_MAPPING="3" # Padrão para 'enable'
MESSAGE="reativado"

if [[ "$ACTION" == "disable" ]]; then
    TARGET_MAPPING="1" # Mapeia o botão direito (3) para o esquerdo (1)
    MESSAGE="desativado"
elif [[ "$ACTION" != "enable" ]]; then
    echo "Erro: Ação inválida. Use 'enable' ou 'disable'." >&2
    exit 1
fi

# O comando 'xinput' precisa do ambiente gráfico.
# O script Python que chama este deve garantir que DISPLAY e XAUTHORITY estão definidos.
if ! command -v xinput &> /dev/null; then
    echo "Erro: O comando 'xinput' não foi encontrado na máquina remota." >&2
    exit 1
fi

# Encontra IDs de dispositivos de mouse/touchpad, ignorando teclados.
DEVICE_IDS=$(xinput list | awk '
    /slave/ && (tolower($0) ~ /mouse|touchpad/) && (tolower($0) !~ /keyboard/) {
        for (i=1; i<=NF; i++) {
            if ($i ~ /^id=[0-9]+$/) {
                split($i, a, "=");
                print a[2];
            }
        }
    }
')

if [ -z "$DEVICE_IDS" ]; then
    echo "Nenhum dispositivo de mouse ou touchpad encontrado."
    exit 0
fi

SUCCESS_COUNT=0

for id in $DEVICE_IDS; do
    NEW_MAP=$(xinput get-button-map "$id" | awk -v map_val="$TARGET_MAPPING" '{$3=map_val; print $0}')
    xinput set-button-map "$id" $NEW_MAP && SUCCESS_COUNT=$((SUCCESS_COUNT+1))
done

echo "Clique direito do mouse ${MESSAGE} em $SUCCESS_COUNT dispositivo(s)."